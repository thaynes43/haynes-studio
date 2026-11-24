"""Use the explicitly supplied migration connection and its isolated search path."""

from alembic import context


def run_migrations() -> None:
    context.configure(connection=context.config.attributes["connection"])
    with context.begin_transaction():
        context.run_migrations()


# Alembic loads the environment as a script, outside the import package.
if not __package__:
    run_migrations()
