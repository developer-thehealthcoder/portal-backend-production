"""
Environment Manager for Multi-Environment Athena Health API Support

SECURITY RECOMMENDATION: Use separate deployments/containers for sandbox and production.
Set DEPLOYMENT_ENVIRONMENT environment variable at deployment time to lock the environment.

For backward compatibility, header/query parameter switching is still supported but NOT RECOMMENDED
for production use due to security risks.
"""

import os
import logging
from typing import Optional, Literal
from enum import Enum
from functools import lru_cache

logger = logging.getLogger(__name__)

class AthenaEnvironment(str, Enum):
    """Athena Health API Environment Types"""
    SANDBOX = "sandbox"
    PRODUCTION = "production"

class EnvironmentManager:
    """
    Manages environment-specific Athena Health API credentials.
    
    SECURITY: Environment is determined by:
    1. DEPLOYMENT_ENVIRONMENT env var (set at deployment - RECOMMENDED for production)
    2. Header: X-Athena-Environment (NOT RECOMMENDED - security risk)
    3. Query parameter: environment (NOT RECOMMENDED - security risk)
    4. Default: sandbox (for safety)
    """
    
    # Get deployment-time environment (set in Azure Container App configuration)
    _DEPLOYMENT_ENV = os.getenv("DEPLOYMENT_ENVIRONMENT", "").lower()
    
    @staticmethod
    def get_athena_credentials(environment: AthenaEnvironment) -> dict:
        """
        Get Athena Health API credentials for specified environment
        
        Args:
            environment: AthenaEnvironment.SANDBOX or AthenaEnvironment.PRODUCTION
            
        Returns:
            Dictionary with credentials: client_id, client_secret, practice_id, base_url
        """
        if environment == AthenaEnvironment.SANDBOX:
            return {
                "client_id": os.getenv("ATHENA_Client_ID"),
                "client_secret": os.getenv("ATHENA_Client_Secret"),
                "practice_id": os.getenv("ATHENA_PRACTICE_ID"),
                "base_url": os.getenv("ATHENA_SANDBOX_API_BASE_URL", "https://api.preview.platform.athenahealth.com/v1"),
            }
        elif environment == AthenaEnvironment.PRODUCTION:
            return {
                "client_id": os.getenv("ATHENA_PRODUCTION_CLIENT_ID"),
                "client_secret": os.getenv("ATHENA_PRODUCTION_CLIENT_SECRET"),
                "practice_id": os.getenv("ATHENA_PRODUCTION_PRACTICE_ID"),
                "base_url": os.getenv("ATHENA_PRODUCTION_API_BASE_URL", "https://api.platform.athenahealth.com/v1"),
            }
        else:
            raise ValueError(f"Unknown environment: {environment}")
    
    @staticmethod
    def parse_environment(
        header_value: Optional[str] = None,
        query_param: Optional[str] = None,
        default: AthenaEnvironment = AthenaEnvironment.SANDBOX
    ) -> AthenaEnvironment:
        """
        Parse environment from various sources with priority:
        1. DEPLOYMENT_ENVIRONMENT env var (set at deployment - SAFEST)
        2. Header (X-Athena-Environment) - NOT RECOMMENDED for production
        3. Query parameter (environment) - NOT RECOMMENDED for production
        4. Default (sandbox for safety)
        
        Args:
            header_value: Value from X-Athena-Environment header
            query_param: Value from environment query parameter
            default: Default environment if none specified
            
        Returns:
            AthenaEnvironment enum value
        """
        # Priority 1: DEPLOYMENT_ENVIRONMENT (set at deployment time - SAFEST)
        if EnvironmentManager._DEPLOYMENT_ENV:
            try:
                env = AthenaEnvironment(EnvironmentManager._DEPLOYMENT_ENV)
                logger.info(f"Using deployment-locked environment: {env.value} (from DEPLOYMENT_ENVIRONMENT)")
                # If header/query tries to override, log a security warning
                if header_value or query_param:
                    logger.warning(
                        f"SECURITY WARNING: Attempted to override deployment-locked environment "
                        f"({env.value}) via header/query. Override ignored for security."
                    )
                return env
            except ValueError:
                logger.error(f"Invalid DEPLOYMENT_ENVIRONMENT value: {EnvironmentManager._DEPLOYMENT_ENV}, falling back to default")
        
        # Priority 2: Header (NOT RECOMMENDED - security risk)
        if header_value:
            try:
                env = AthenaEnvironment(header_value.lower())
                logger.warning(
                    f"SECURITY WARNING: Using environment from header: {env.value}. "
                    f"Consider using separate deployments with DEPLOYMENT_ENVIRONMENT instead."
                )
                return env
            except ValueError:
                logger.warning(f"Invalid environment in header: {header_value}, using default")
        
        # Priority 3: Query parameter (NOT RECOMMENDED - security risk)
        if query_param:
            try:
                env = AthenaEnvironment(query_param.lower())
                logger.warning(
                    f"SECURITY WARNING: Using environment from query parameter: {env.value}. "
                    f"Consider using separate deployments with DEPLOYMENT_ENVIRONMENT instead."
                )
                return env
            except ValueError:
                logger.warning(f"Invalid environment in query param: {query_param}, using default")
        
        # Priority 4: Default
        logger.info(f"Using default environment: {default.value}")
        return default

# Global instance
environment_manager = EnvironmentManager()

