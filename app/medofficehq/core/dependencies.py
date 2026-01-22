from fastapi import Header, Query
from typing import Optional
from app.medofficehq.services.athena_service import AthenaService
from app.medofficehq.core.environment_manager import (
    environment_manager,
    AthenaEnvironment
)


def get_athena_service(
    x_athena_environment: Optional[str] = Header(None, alias="X-Athena-Environment"),
    environment: Optional[str] = Query(None)
) -> AthenaService:
    """
    Dependency function to get an instance of AthenaService with environment-specific credentials.

    Environment can be specified via:
    - Header: X-Athena-Environment (sandbox/production)  <-- recommended
    - Query parameter: ?environment=sandbox|production   <-- optional fallback
    - Default: sandbox (for safety)

    Args:
        x_athena_environment: Environment from X-Athena-Environment header
        environment: Environment from query parameter

    Returns:
        AthenaService instance configured for the specified environment
    """
    # Parse environment (header > query > default)
    env = environment_manager.parse_environment(
        header_value=x_athena_environment,
        query_param=environment,
        default=AthenaEnvironment.SANDBOX
    )

    # Get credentials for the environment
    credentials = environment_manager.get_athena_credentials(env)

    # Create AthenaService with environment-specific credentials
    return AthenaService(
        client_id=credentials["client_id"],
        client_secret=credentials["client_secret"],
        practice_id=credentials["practice_id"],
        base_url=credentials["base_url"],
        environment=env.value
    )