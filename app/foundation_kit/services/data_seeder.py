from app.foundation_kit.database.cosmos import get_container
from app.config import COSMOS_CONTAINER_USER_GROUPS, COSMOS_CONTAINER_MENU
from fastapi import HTTPException
from typing import List, Dict, Any
import uuid
from datetime import datetime, UTC

class DataSeeder:
    """Service for seeding essential data into new databases."""
    
    @staticmethod
    def get_default_user_groups() -> List[Dict[str, Any]]:
        """Get the default user groups that should be seeded in every new database."""
        now = datetime.now(UTC).isoformat()
        
        return [
            {
                "id": "system-admin",
                "name": "System Admin",
                "tag": "SystemAdmin",
                "description": "Full system access with all permissions",
                "created_at": now,
                "updated_at": now
            },
            {
                "id": "institution-admin",
                "name": "Institution Admin",
                "tag": "InstitutionAdmin",
                "description": "Administrator for specific institutions",
                "created_at": now,
                "updated_at": now
            }
        ]
    
    @staticmethod
    def get_default_menu() -> List[Dict[str, Any]]:
        """Get the default menu structure that should be seeded in every new database."""
        
        return [{
            "menu": [
                {
                    "id": "admin-menu",
                    "name": "Admin",
                    "icon": "Shield",
                    "allowed_roles": [
                        "SystemAdmin",
                        "InstitutionAdmin"
                    ],
                    "sub_menu": [
                        {
                            "id": "users-submenu",
                            "name": "Users",
                            "url": "/users",
                            "allowed_roles": [
                                "SystemAdmin",
                                "InstitutionAdmin"
                            ]
                        },
                        {
                            "id": "institutions-submenu",
                            "name": "Institutions",
                            "url": "/institutions",
                            "allowed_roles": [
                                "SystemAdmin"
                            ]
                        },
                        {
                            "id": "user-groups-submenu",
                            "name": "User Groups",
                            "url": "/user-groups",
                            "allowed_roles": [
                                "SystemAdmin",
                                "InstitutionAdmin"
                            ]
                        }
                    ]
                }
            ]
        }]
    
    @staticmethod
    def seed_user_groups() -> Dict[str, Any]:
        """Seed default user groups into the database."""
        try:
            container = get_container(COSMOS_CONTAINER_USER_GROUPS)
            default_groups = DataSeeder.get_default_user_groups()
            
            seeded_count = 0
            skipped_count = 0
            
            for group in default_groups:
                try:
                    # Check if group already exists
                    existing = container.read_item(item=group["id"], partition_key=group["id"])
                    skipped_count += 1
                except Exception:
                    # Group doesn't exist, create it
                    container.create_item(body=group)
                    seeded_count += 1
            
            return {
                "message": "User groups seeding completed",
                "seeded": seeded_count,
                "skipped": skipped_count,
                "total": len(default_groups)
            }
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to seed user groups: {str(e)}"
            )
    
    @staticmethod
    def seed_menu() -> Dict[str, Any]:
        """Seed default menu structure into the database."""
        try:
            container = get_container(COSMOS_CONTAINER_MENU)
            default_menu_data = DataSeeder.get_default_menu()
            
            seeded_count = 0
            skipped_count = 0
            
            # Extract the actual menu items from the structure
            menu_items = default_menu_data
            now = datetime.now(UTC).isoformat()
            
            for menu_item in menu_items:
                # Add required fields for Cosmos DB
                menu_doc = {
                    "id": menu_item.get("id", str(uuid.uuid4())),
                    "created_at": now,
                    "updated_at": now,
                    **menu_item
                }
                
                try:
                    # Check if menu already exists
                    existing = container.read_item(item=menu_doc["id"], partition_key=menu_doc["id"])
                    skipped_count += 1
                except Exception:
                    # Menu doesn't exist, create it
                    container.create_item(body=menu_doc)
                    seeded_count += 1
            
            return {
                "message": "Menu seeding completed",
                "seeded": seeded_count,
                "skipped": skipped_count,
                "total": len(menu_items)
            }
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to seed menu: {str(e)}"
            )
    
    @staticmethod
    def seed_all() -> Dict[str, Any]:
        """Seed all essential data into the database."""
        try:
            user_groups_result = DataSeeder.seed_user_groups()
            menu_result = DataSeeder.seed_menu()
            
            return {
                "message": "All data seeding completed",
                "user_groups": user_groups_result,
                "menu": menu_result
            }
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to seed all data: {str(e)}"
            )
    
    @staticmethod
    def export_user_groups() -> List[Dict[str, Any]]:
        """Export current user groups for backup or migration."""
        try:
            container = get_container(COSMOS_CONTAINER_USER_GROUPS)
            query = "SELECT * FROM c"
            groups = list(container.query_items(query=query, enable_cross_partition_query=True))
            return groups
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to export user groups: {str(e)}"
            )

# example data in foundation kit

# user data

# {
#     "id": "985a2ee8-9d50-402d-a2f8-7a2b3ffa7bc9",
#     "first_name": "Hameed",
#     "last_name": "Ur Rehman",
#     "email": "hameed@tellurium.me",
#     "hashed_password": "$2b$12$WwqmX2e4Np9zBLo27jTWMu7Hj4sg1VQ36f8/cwb.ktHmp4hfIbn02",
#     "roles": [
#         "473cfa18-ac70-446e-b8fc-30ee8457ca3c",
#         "f7953165-142a-4710-8909-a7b1c8c09db2"
#     ],
#     "institutions": [
#         "8cbc616a-1ce3-4506-9b32-f7d0cfbbe410"
#     ],
#     "is_active": true,
#     "last_login": "2025-07-04T23:56:22.468956+00:00",
#     "created_at": "2025-06-13T19:12:07.546946+00:00",
#     "updated_at": "2025-06-16T15:09:26.897148+00:00",
#     "_rid": "7C8aANLf1OkfAAAAAAAAAA==",
#     "_self": "dbs/7C8aAA==/colls/7C8aANLf1Ok=/docs/7C8aANLf1OkfAAAAAAAAAA==/",
#     "_etag": "\"07001a85-0000-4d00-0000-68686a260000\"",
#     "_attachments": "attachments/",
#     "selected_institution": "8cbc616a-1ce3-4506-9b32-f7d0cfbbe410",
#     "_ts": 1751673382
# }

# menu data

# {
#     "menu": [
#         {
#             "name": "Admin",
#             "icon": "Shield",
#             "allowed_roles": [
#                 "SystemAdmin",
#                 "InstitutionAdmin"
#             ],
#             "sub_menu": [
#                 {
#                     "name": "Users",
#                     "url": "/users",
#                     "allowed_roles": [
#                         "SystemAdmin",
#                         "InstitutionAdmin"
#                     ]
#                 },
#                 {
#                     "name": "Institutions",
#                     "url": "/institutions",
#                     "allowed_roles": [
#                         "SystemAdmin"
#                     ]
#                 },
#                 {
#                     "name": "User Groups",
#                     "url": "/user-groups",
#                     "allowed_roles": [
#                         "SystemAdmin",
#                         "InstitutionAdmin"
#                     ]
#                 }
#             ]
#         }
#     ],
#     "id": "db29a2b4-dd1a-441e-b192-2bd23a8675e9",
#     "_rid": "7C8aAIPMhlUCAAAAAAAAAA==",
#     "_self": "dbs/7C8aAA==/colls/7C8aAIPMhlU=/docs/7C8aAIPMhlUCAAAAAAAAAA==/",
#     "_etag": "\"45006fe4-0000-4d00-0000-685038880000\"",
#     "_attachments": "attachments/",
#     "_ts": 1750087816
# }

# user group data

# {
#     "id": "473cfa18-ac70-446e-b8fc-30ee8457ca3c",
#     "name": "System Admin",
#     "tag": "SystemAdmin",
#     "description": "",
#     "created_at": "2025-06-04T10:43:10.315523+00:00",
#     "updated_at": "2025-06-04T10:43:10.315523+00:00",
#     "_rid": "7C8aAJ1A0FsCAAAAAAAAAA==",
#     "_self": "dbs/7C8aAA==/colls/7C8aAJ1A0Fs=/docs/7C8aAJ1A0FsCAAAAAAAAAA==/",
#     "_etag": "\"350032b0-0000-4d00-0000-6840233e0000\"",
#     "_attachments": "attachments/",
#     "_ts": 1749033790
# }

# institution data

# {
#     "id": "8cbc616a-1ce3-4506-9b32-f7d0cfbbe410",
#     "name": "Athena Health",
#     "description": "The health coder",
#     "user_groups": [
#         "473cfa18-ac70-446e-b8fc-30ee8457ca3c",
#         "f7953165-142a-4710-8909-a7b1c8c09db2"
#     ],
#     "created_at": "2025-06-16T10:43:33.439492+00:00",
#     "updated_at": "2025-06-16T15:10:36.758069+00:00",
#     "_rid": "7C8aAOO9ePMNAAAAAAAAAA==",
#     "_self": "dbs/7C8aAA==/colls/7C8aAOO9ePM=/docs/7C8aAOO9ePMNAAAAAAAAAA==/",
#     "_etag": "\"0c003f3b-0000-4d00-0000-685033ec0000\"",
#     "_attachments": "attachments/",
#     "_ts": 1750086636
# }
 