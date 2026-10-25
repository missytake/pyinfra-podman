import importlib.resources

from pyinfra import host
from pyinfra.facts.files import File
from pyinfra.operations import files, server, systemd


# XXX network?
def container(
    image: str,
    unix_user: str,
    name: str = "",
    environment: dict = {},
    mounts: [tuple] = [],
    ports: [str] = [],
    restart: bool = False,
    enabled: bool = True,
    running: bool = True,
):
    """Run (and restart) a podman container as a systemd user unit.

    :param image: the docker image + version
    :param unix_user: the UNIX user which runs the podman container
    :param name: must be unique for the unix_user
    :param environment: the environment variables the container users
    :param mounts: the directories mounted into the container
    :param ports: the port pairings the container exposes, as passed to podman run -p
    :param restart: whether to restart the container
    :param enabled: whether to start the systemd unit on reboot
    :param running: whether to start the systemd unit in this function already
    """
    if not name:
        name = image

    unprivileged = dict(_su_user=unix_user, _use_su_login=True)
    env_path = f"/home/{unix_user}/.env"
    for key, value in environment.items():
        env = files.line(
            name=f"Set {key} in {env_path}",
            path=env_path,
            line=f"^(#|){key}=(.*)",
            replace=f"{key}={value}",
            extended_regex=True,
            **unprivileged,
        )
        restart |= env.changed

    server.shell(
        name=f"podman pull {image}",
        commands=[f"podman pull docker.io/{image}"],
    )

    mount_list = []
    for source, destination in mounts:
        mount_list.append(
            f"--mount type=bind,source={source},destination={destination}"
        )

    service_path = f"/home/{unix_user}/.config/systemd/user/"
    unit = files.template(
        name=f"configure {name} systemd unit",
        src=importlib.resources.files(__package__) / "podman.service.j2",
        dest=f"{service_path}{name}.service",
        description=f"run {image} podman container",
        mount=" ".join(mount_list),
        port=" ".join([f"-p={port_pairing}" for port_pairing in ports]),
        container_name=name,
        image=image,
        env_path=env_path,
        **unprivileged,
    )
    restart |= unit.changed

    systemd.service(
        name=f"run {name} service",
        service=f"{name}.service",
        enabled=enabled,
        running=running,
        restarted=restart,
        daemon_reload=unit.changed,
        user_name=unix_user,
        user_mode=True,
        **unprivileged,
    )
    if enabled:
        if not host.get_fact(File, f"/var/lib/systemd/linger/{unix_user}"):
            server.shell(
                name=f"enable {unix_user}'s systemd units to auto-start at boot",
                commands=[f"loginctl enable-linger {unix_user}"],
            )
        files.line(
            name=f"{unix_user} .profile: ensure XDG_RUNTIME_DIR",
            path=f"/home/{unix_user}/.profile",
            line='export XDG_RUNTIME_DIR="/run/user/$UID"',
            **unprivileged,
        )
        files.line(
            name=f"{unix_user} .profile: ensure DBUS_SESSION_BUS_ADDRESS",
            path=f"/home/{unix_user}/.profile",
            line='export DBUS_SESSION_BUS_ADDRESS="unix:path=${XDG_RUNTIME_DIR}/bus"',
            **unprivileged,
        )
