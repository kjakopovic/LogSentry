from typing import Annotated

import typer

from logsentry import __version__

app = typer.Typer(help="Nadzor i analiza logova udaljenog servera.", no_args_is_help=True)


def _print_version(value: bool) -> None:
    if value:
        typer.echo(f"logsentry {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option("--version", help="Ispiši verziju.", callback=_print_version, is_eager=True),
    ] = False,
) -> None:
    pass
