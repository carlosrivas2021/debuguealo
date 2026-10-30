"""Saved launch fixtures for the profile-owned dashboard workflow."""


def save_remembered_profile(app, project_name, name="Orders"):
    project = app._compose_projects[project_name]
    app._launch_store.save_configuration(
        {
            "name": name,
            "type": "docker-compose",
            "projectName": project_name,
            "workspaceFolder": str(project.workspace),
            "cwd": str(project.process_cwd or project.workspace),
            "files": list(map(str, project.files)),
            "projectDirectory": str(project.project_directory or project.workspace),
        }
    )
