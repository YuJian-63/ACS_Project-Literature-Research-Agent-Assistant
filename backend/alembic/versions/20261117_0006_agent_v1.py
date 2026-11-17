"""Store isolated Agent v1 requests and native results without legacy chunk identities."""

from alembic import op

revision = "20261117_0006"
down_revision = "20261115_0005"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TABLE tasks ADD COLUMN agent_input jsonb, ADD COLUMN agent_result jsonb"
    )
    op.execute(
        "ALTER TABLE tasks ADD CONSTRAINT tasks_agent_input_object CHECK (agent_input IS NULL OR jsonb_typeof(agent_input) = 'object')"
    )
    op.execute(
        "ALTER TABLE tasks ADD CONSTRAINT tasks_agent_result_object CHECK (agent_result IS NULL OR jsonb_typeof(agent_result) = 'object')"
    )
    op.execute("ALTER TABLE tasks DROP CONSTRAINT tasks_runner_type_check")
    op.execute(
        "ALTER TABLE tasks ADD CONSTRAINT tasks_runner_type_check CHECK (runner_type IN ('mock', 'langgraph', 'agent'))"
    )
    op.execute("ALTER TABLE tasks ALTER COLUMN max_tokens DROP NOT NULL")
    op.execute("ALTER TABLE tasks DROP CONSTRAINT tasks_max_tokens_check")
    op.execute(
        "ALTER TABLE tasks ADD CONSTRAINT tasks_token_policy CHECK ((runner_type = 'agent' AND max_tokens IS NULL) OR (runner_type <> 'agent' AND max_tokens BETWEEN 1 AND 100000 AND max_tokens IS NOT NULL))"
    )


def downgrade():
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM tasks WHERE runner_type = 'agent' OR agent_input IS NOT NULL OR agent_result IS NOT NULL) THEN RAISE EXCEPTION 'Refusing downgrade: Agent tasks must be preserved'; END IF; END $$"
    )
    op.execute("ALTER TABLE tasks DROP CONSTRAINT tasks_token_policy")
    op.execute("ALTER TABLE tasks ALTER COLUMN max_tokens SET NOT NULL")
    op.execute(
        "ALTER TABLE tasks ADD CONSTRAINT tasks_max_tokens_check CHECK (max_tokens BETWEEN 1 AND 100000)"
    )
    op.execute("ALTER TABLE tasks DROP CONSTRAINT tasks_runner_type_check")
    op.execute(
        "ALTER TABLE tasks ADD CONSTRAINT tasks_runner_type_check CHECK (runner_type IN ('mock', 'langgraph'))"
    )
    op.execute("ALTER TABLE tasks DROP COLUMN agent_input, DROP COLUMN agent_result")
