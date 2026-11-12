"""Remove what the Docker smoke tests create, and nothing else on the machine."""

import subprocess

IMAGE_NAME = "hca-dataset-validator:test"


def remove_test_artifacts(image_name: str = IMAGE_NAME) -> None:
    """Force-remove the containers started from ``image_name``, then the image itself."""
    listed = subprocess.run(
        ["docker", "ps", "-a", "--filter", f"ancestor={image_name}", "-q"], capture_output=True, text=True
    )
    container_ids = listed.stdout.split()
    if container_ids:
        subprocess.run(["docker", "rm", "-f", *container_ids], capture_output=True)
    subprocess.run(["docker", "rmi", "-f", image_name], capture_output=True)
