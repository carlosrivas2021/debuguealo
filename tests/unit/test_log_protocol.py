import io
import struct

import pytest

from debugpilot.core.exceptions import DockerError
from debugpilot.core.models import ContainerInfo, LogEntry
from debugpilot.docker.logs import LogBuffer, LogDecoder, ReplayCursor, read_frames


def entry(text="hello", timestamp="2026-10-26T18:00:00.123456789Z", stream="stdout"):
    return LogEntry(timestamp=timestamp, stream=stream, text=text)


def test_container_metadata_and_compose_labels():
    container = ContainerInfo.from_docker(
        {
            "Id": "abc123",
            "Names": ["/payments-api"],
            "Image": "payments:dev",
            "State": "exited",
            "Created": 1_700_000_000,
            "Ports": [{"PrivatePort": 8000, "PublicPort": 8080, "IP": "127.0.0.1", "Type": "tcp"}],
            "Labels": {
                "com.docker.compose.project": "demo",
                "com.docker.compose.service": "payments",
            },
        }
    )
    assert container.name == "payments-api"
    assert container.state == "exited"
    assert container.compose_project == "demo"
    assert container.compose_service == "payments"
    assert container.ports[0].public_port == 8080
    assert container.created_at.year == 2023


def test_plain_docker_container_without_compose_or_published_ports():
    container = ContainerInfo.from_docker({"Id": "abc", "Image": "demo", "Created": 0})
    assert container.name == "abc"
    assert container.compose_project is None
    assert container.ports == ()


def test_frame_decoder_preserves_stdout_stderr_and_rejects_oversized_or_truncated():
    def frame(stream, data):
        return struct.pack(">BxxxI", stream, len(data)) + data

    raw = frame(1, b"a\n") + frame(2, b"b\n")
    assert list(read_frames(io.BytesIO(raw), tty=False)) == [("stdout", b"a\n"), ("stderr", b"b\n")]
    for raw in (b"short", struct.pack(">BxxxI", 1, 2_000_000), frame(1, b"long")[:-1]):
        with pytest.raises(DockerError):
            list(read_frames(io.BytesIO(raw), tty=False))
    assert list(read_frames(io.BytesIO(b"tty\n"), tty=True)) == [("combined", b"tty\n")]


def test_log_decoder_handles_partial_utf8_and_infers_severity():
    decoder = LogDecoder(max_line_bytes=100)
    raw = "2026-10-26T18:00:00.123456789Z ERROR café\n".encode()
    assert decoder.feed("stderr", raw[:-2]) == []
    logs = decoder.feed("stderr", raw[-2:])
    assert len(logs) == 1
    assert logs[0].text == "ERROR café"
    assert logs[0].timestamp.endswith("123456789Z")
    assert logs[0].severity == "error"
    assert logs[0].stream == "stderr"


def test_oversized_line_is_truncated_once_and_memory_is_bounded():
    decoder = LogDecoder(max_line_bytes=64)
    logs = decoder.feed("stdout", b"x" * 100_000)
    assert len(logs) == 1 and logs[0].truncated
    assert len(logs[0].text) <= 64
    assert decoder.buffered_bytes <= 64
    assert decoder.feed("stdout", b"more\nnext\n")[0].text == "next"


def test_ring_buffer_bounds_entries_bytes_and_filters():
    buffer = LogBuffer(max_entries=2, max_bytes=100)
    buffer.append(entry("first"))
    buffer.append(entry("INFO second"))
    buffer.append(entry("ERROR third").model_copy(update={"severity": "error"}))
    assert [log.text for log in buffer.entries()] == ["INFO second", "ERROR third"]
    assert [log.text for log in buffer.entries(text="third", severity="error")] == ["ERROR third"]
    assert buffer.byte_size <= 100
    buffer.clear()
    assert buffer.entries() == () and buffer.byte_size == 0


def test_reconnect_replay_preserves_legitimate_duplicate_multiplicity():
    cursor = ReplayCursor(capacity=4)
    assert cursor.accept(entry("same"))
    assert cursor.accept(entry("same"))
    cursor.reconnecting()
    assert cursor.since is not None
    assert not cursor.accept(entry("same"))
    assert not cursor.accept(entry("same"))
    assert cursor.accept(entry("same"))  # A new third identical record must survive.
    assert cursor.accept(entry("next", "2026-10-26T18:00:01.000000001Z"))


def test_reconnect_without_timestamps_or_beyond_window_fails_explicitly():
    for values in ([entry(timestamp=None)], [entry("a"), entry("b")]):
        cursor = ReplayCursor(capacity=1)
        for value in values:
            cursor.accept(value)
        with pytest.raises(DockerError):
            cursor.reconnecting()


def test_initial_stdout_stderr_time_skew_does_not_drop_records():
    cursor = ReplayCursor()
    assert cursor.accept(entry("stderr first", "2026-10-26T18:00:01.000000001Z", "stderr"))
    assert cursor.accept(entry("delayed stdout", "2026-10-26T18:00:00.999999999Z"))
