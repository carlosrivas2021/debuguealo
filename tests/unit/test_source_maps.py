"""Source map decoding and the workspace index that maps .ts lines to generated .js."""

import json

import pytest

from debugpilot.debugger.source_maps import SourceMapIndex, decode_mappings, load_source_map

_B64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'


def vlq(value):
    """Test-side encoder: the standard base64 VLQ, independent of the decoder."""
    value = (-value << 1) | 1 if value < 0 else value << 1
    out = ''
    while True:
        digit, value = value & 31, value >> 5
        out += _B64[digit | (32 if value else 0)]
        if not value:
            return out


def encode(lines):
    """lines: per generated line, a list of (gen_col, source, orig_line, orig_col), 0-based."""
    state = [0, 0, 0]
    encoded = []
    for segments in lines:
        column = 0
        parts = []
        for gen_col, source, orig_line, orig_col in segments:
            parts.append(vlq(gen_col - column) + vlq(source - state[0])
                         + vlq(orig_line - state[1]) + vlq(orig_col - state[2]))
            column, state = gen_col, [source, orig_line, orig_col]
        encoded.append(','.join(parts))
    return ';'.join(encoded)


def test_vlq_digits_follow_the_specification():
    assert [vlq(n) for n in (0, 1, -1, 15, 16, -16)] == ['A', 'C', 'D', 'e', 'gB', 'hB']
    assert decode_mappings('AAAA;AACA,EAAE;;gBAAgB') == [
        [(0, 0, 0, 0)], [(0, 0, 1, 0), (2, 0, 1, 2)], [], [(16, 0, 1, 18)]]


def test_decoding_round_trips_relative_fields_across_lines():
    lines = [[], [(4, 0, 2, 0), (10, 1, 0, 3)], [(0, 0, 5, 1)], [], [(2, 1, 1, 0)]]
    assert decode_mappings(encode(lines)) == lines


def test_segments_with_only_a_generated_column_are_ignored():
    # One-field segments map generated code to no source.
    assert decode_mappings('A,CAAC') == [[(1, 0, 0, 1)]]


@pytest.mark.parametrize('mappings', ['!', 'A$', 'AA', 'AAAAA' * 0 + 'g'])
def test_malformed_mappings_are_rejected(mappings):
    with pytest.raises(ValueError):
        decode_mappings(mappings)


def project(tmp_path, maps):
    """maps: {generated relative path: (sources, lines)}; writes .js and .js.map files."""
    for generated, (sources, lines) in maps.items():
        path = tmp_path / generated
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'// generated\n//# sourceMappingURL={path.name}.map\n')
        (tmp_path / f'{generated}.map').write_text(json.dumps({
            'version': 3, 'file': path.name, 'sources': sources, 'names': [],
            'mappings': encode(lines)}))
    return tmp_path


def test_load_resolves_sources_relative_to_the_map_and_source_root(tmp_path):
    root = project(tmp_path, {'dist/main.js': (['../src/main.ts'], [[(0, 0, 0, 0)]])})
    loaded = load_source_map(root / 'dist/main.js.map')
    assert loaded.generated == (root / 'dist/main.js').resolve()
    assert loaded.sources == ((root / 'src/main.ts').resolve(),)
    data = json.loads((root / 'dist/main.js.map').read_text())
    data.update(sourceRoot='../lib/', sources=['util.ts'])
    (root / 'dist/main.js.map').write_text(json.dumps(data))
    assert load_source_map(root / 'dist/main.js.map').sources == (
        (root / 'lib/util.ts').resolve(),)


def test_generated_and_original_positions_follow_tsc_like_output(tmp_path):
    # tsc adds two prelude lines, so .ts line 3 (0-based 2) becomes .js line 5 (0-based 4).
    lines = [[], [], [(0, 0, 0, 0)], [(0, 0, 1, 0)], [(4, 0, 2, 2), (10, 0, 2, 8)], [],
             [(0, 0, 4, 0)]]
    root = project(tmp_path, {'dist/main.js': (['../src/main.ts'], lines)})
    index = SourceMapIndex(root)
    source = (root / 'src/main.ts').resolve()
    generated = (root / 'dist/main.js').resolve()
    assert index.generated_position(source, 3) == (generated, 5, 4)
    assert index.generated_position(source, 1) == (generated, 3, 0)
    # A line with no code (4) maps nowhere; the debugger then reports it unverified.
    assert index.generated_position(source, 4) is None
    assert index.original_position(generated, 5, 12) == (source, 3)
    assert index.original_position(generated, 5, 0) == (source, 3)
    assert index.original_position(generated, 7, 9) == (source, 5)
    assert index.original_position(generated, 6, 0) is None
    assert index.original_position(generated, 1, 0) is None
    assert index.original_position(root / 'other.js', 1, 0) is None


def test_index_skips_node_modules_and_git_and_sources_outside_the_root(tmp_path):
    root = project(tmp_path, {
        'dist/a.js': (['../src/a.ts', '../../outside.ts'], [[(0, 0, 0, 0)], [(0, 1, 0, 0)]]),
        'node_modules/pkg/index.js': (['../../src/a.ts'], [[(0, 0, 9, 0)]]),
        '.git/x.js': (['../src/a.ts'], [[(0, 0, 9, 0)]]),
    })
    index = SourceMapIndex(root)
    source = (root / 'src/a.ts').resolve()
    assert index.generated_position(source, 1) == ((root / 'dist/a.js').resolve(), 1, 0)
    assert index.generated_position(source, 10) is None
    assert index.original_position((root / 'dist/a.js').resolve(), 2, 0) is None


def test_invalid_or_oversized_maps_are_skipped_not_fatal(tmp_path, monkeypatch):
    root = project(tmp_path, {'dist/good.js': (['../src/good.ts'], [[(0, 0, 0, 0)]])})
    (root / 'dist/bad.js.map').write_text('{not json')
    (root / 'dist/sections.js.map').write_text(json.dumps({'version': 3, 'sections': []}))
    (root / 'dist/v2.js.map').write_text(json.dumps({'version': 2, 'sources': [], 'mappings': ''}))
    limit = (root / 'dist/good.js.map').stat().st_size
    (root / 'dist/big.js.map').write_text(json.dumps({
        'version': 3, 'sources': ['../src/big.ts'], 'mappings': 'AAAA', 'pad': ' ' * limit}))
    monkeypatch.setattr('debugpilot.debugger.source_maps.MAX_MAP_BYTES', limit)
    index = SourceMapIndex(root)
    assert index.generated_position((root / 'src/good.ts').resolve(), 1) is not None
    assert not index.maps(root / 'src/big.ts')


def test_index_stops_at_its_file_limit(tmp_path, monkeypatch):
    root = project(tmp_path, {f'dist/m{n}.js': ([f'../src/m{n}.ts'], [[(0, 0, 0, 0)]])
                              for n in range(5)})
    monkeypatch.setattr('debugpilot.debugger.source_maps.MAX_MAP_FILES', 3)
    index = SourceMapIndex(root)
    found = [n for n in range(5)
             if index.generated_position((root / f'src/m{n}.ts').resolve(), 1)]
    assert len(found) == 3
