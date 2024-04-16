import subprocess


def isort() -> None:
    subprocess.run(["isort", "."], check=True)


def black() -> None:
    subprocess.run(["black", "."], check=True)


def flake8() -> None:
    subprocess.run(["flake8"], check=True)


def mypy() -> None:
    subprocess.run(["mypy", "."], check=True)


def style() -> None:
    isort()
    black()
    flake8()
    mypy()
