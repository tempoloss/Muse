from alembic import context
from sqlalchemy import URL, create_engine

engine = create_engine(URL.create("sqlite", database=str(context.config.attributes["database"])))
try:
    with engine.connect() as connection:
        context.configure(connection=connection, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()
finally:
    engine.dispose()
