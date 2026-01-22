from app.foundation_kit.database.cosmos import get_container
from app.config import COSMOS_CONTAINER_MENU
from fastapi import HTTPException
from typing import List, Optional

def filter_menu_by_role(menu: dict, user_roles: List[str]) -> Optional[dict]:
    """Filter a menu item and its submenus based on user role."""
    # If menu has no role restrictions, it's accessible to all
    if not menu.get("allowed_roles"):
        return menu
    
    # If menu has role restrictions, check if user's role is allowed
    if not any(role in user_roles for role in menu.get("allowed_roles", [])):
        return None
    
    # Filter submenus based on role
    filtered_submenus = []
    for submenu in menu.get("sub_menu", []):
        # Handle both string and list allowed_roles
        submenu_roles = submenu.get("allowed_roles", [])
        if isinstance(submenu_roles, str):
            submenu_roles = [submenu_roles]
            
        if not submenu_roles or any(role in user_roles for role in submenu_roles):
            filtered_submenus.append(submenu)
    
    # Create a new menu dict with filtered submenus
    filtered_menu = menu.copy()
    filtered_menu["sub_menu"] = filtered_submenus
    return filtered_menu

def get_menu_list(user_roles: List[str]):
    try:
        container = get_container(COSMOS_CONTAINER_MENU)
        # Query all menu items
        query = "SELECT * FROM c"
        items = list(container.query_items(query=query, enable_cross_partition_query=True))
        
        # Process items and filter based on role
        menus = []
        for item in items:
            # Handle the nested menu structure
            menu_items = item.get("menu", [])
            for menu_item in menu_items:
                menu_data = {
                    "id": item["id"],
                    "name": menu_item.get("name", ""),
                    "description": menu_item.get("description", ""),
                    "icon": menu_item.get("icon", ""),
                    "sub_menu": menu_item.get("sub_menu", []),
                    "allowed_roles": menu_item.get("allowed_roles", [])
                }
                
                # Filter menu based on user role
                filtered_menu = filter_menu_by_role(menu_data, user_roles)
                if filtered_menu:
                    menus.append(filtered_menu)
            
        return {"menus": menus}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# def create_menu(menu_data: dict):
#     try:
#         container = get_container()
#         # Add the menu item to Cosmos DB
#         response = container.create_item(body=menu_data)
#         return response
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))

# def update_menu(menu_id: str, menu_data: dict):
#     try:
#         container = get_container()
#         # Update the menu item in Cosmos DB
#         response = container.replace_item(item=menu_id, body=menu_data)
#         return response
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))

# def delete_menu(menu_id: str):
#     try:
#         container = get_container()
#         # Delete the menu item from Cosmos DB
#         container.delete_item(item=menu_id, partition_key=menu_id)
#         return {"message": "Menu deleted successfully"}
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e)) 