from fastapi import APIRouter, Security, Depends, HTTPException
from app.foundation_kit.services.menu_service import get_menu_list
from app.foundation_kit.routers.auth import get_current_user, get_user_roles
from app.foundation_kit.database.cosmos import get_container
from app.foundation_kit.schemas.user import Institution, UserGroup, UserGroupCreate
from app.config import (
    COSMOS_CONTAINER_INSTITUTIONS, 
    COSMOS_CONTAINER_USER_GROUPS, 
    COSMOS_CONTAINER_USERS,
    COSMOS_CONTAINER_MENU
)
import uuid
from datetime import datetime, UTC

router = APIRouter()

@router.get("/menu/", dependencies=[Security(get_current_user)])
async def menu_list(current_user: dict = Depends(get_current_user)):
    user_roles = get_user_roles(current_user)
    return get_menu_list(user_roles)

@router.post("/institutions/", dependencies=[Security(get_current_user)])
async def create_institution(institution: Institution):
    institution.id = str(uuid.uuid4())
    now = datetime.now(UTC)
    institution.created_at = now.isoformat()
    institution.updated_at = now.isoformat()
    container = get_container(COSMOS_CONTAINER_INSTITUTIONS)
    container.create_item(body=institution.model_dump())
    return {"message": "Institution created successfully."}

@router.patch("/institutions/{institution_id}", dependencies=[Security(get_current_user)])
async def update_institution(institution_id: str, institution: Institution):
    container = get_container(COSMOS_CONTAINER_INSTITUTIONS)
    try:
        query = f"SELECT * FROM c WHERE c.id = '{institution_id}'"
        items = list(container.query_items(query=query, enable_cross_partition_query=True))
        if not items:
            raise HTTPException(status_code=404, detail="Institution not found")
        existing_institution = items[0]
        update_data = institution.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            if value is not None:
                existing_institution[key] = value
        existing_institution['updated_at'] = datetime.now(UTC).isoformat()
        container.replace_item(item=institution_id, body=existing_institution)
        return {"message": "Institution updated successfully."}
    except Exception as e:
        if "NotFound" in str(e):
            raise HTTPException(status_code=404, detail="Institution not found")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/institutions/", dependencies=[Security(get_current_user)])
async def get_institutions(current_user: dict = Depends(get_current_user)):
    container = get_container(COSMOS_CONTAINER_INSTITUTIONS)
    user_roles = get_user_roles(current_user)
    if "SystemAdmin" in user_roles:
        query = "SELECT * FROM c"
        items = list(container.query_items(query=query, enable_cross_partition_query=True))
        return items
    elif "InstitutionAdmin" in user_roles:
        institution_ids = current_user["institutions"]
        if not institution_ids:
            raise HTTPException(status_code=400, detail="Admin user has no associated institutions")
        institution_conditions = " OR ".join([f"c.id = '{inst}'" for inst in institution_ids])
        query = f"SELECT * FROM c WHERE {institution_conditions}"
        items = list(container.query_items(query=query, enable_cross_partition_query=True))
        return items
    else:
        raise HTTPException(status_code=403, detail="Insufficient permissions to view institutions")

@router.delete("/institutions/{institution_id}", dependencies=[Security(get_current_user)])
async def delete_institution(institution_id: str):
    inst_container = get_container(COSMOS_CONTAINER_INSTITUTIONS)
    user_container = get_container(COSMOS_CONTAINER_USERS)
    try:
        inst_container.read_item(institution_id, partition_key=institution_id)
        query = "SELECT * FROM c WHERE ARRAY_CONTAINS(c.institutions, @inst)"
        users = list(user_container.query_items(
            query=query,
            parameters=[{"name":"@inst","value":institution_id}],
            partition_key=None,
            enable_cross_partition_query=True,
        ))
        for u in users:
            u["institutions"] = [i for i in u.get("institutions", []) if i != institution_id]
            user_container.replace_item(
                item=u["id"],
                body=u
            )
        inst_container.delete_item(institution_id, partition_key=institution_id)
    except Exception as e:
        if "NotFound" in str(e):
            raise HTTPException(status_code=404, detail="Institution not found")
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "institution deleted and cleaned up from users"}

@router.get("/current-user-institutions/", dependencies=[Security(get_current_user)])
async def get_user_institutions(current_user: dict = Depends(get_current_user)):
    institutions_container = get_container(COSMOS_CONTAINER_INSTITUTIONS)
    institutions = []

    for inst_id in current_user.get("institutions", []):
        try:
            institution = institutions_container.read_item(inst_id, partition_key=inst_id)
            institutions.append({
                "id": institution["id"],
                "name": institution.get("name", ""),
            })
        except Exception as e:
            continue
    
    return {"institutions": institutions}

@router.get("/user-institutions/{user_id}", dependencies=[Security(get_current_user)])
async def get_user_institutions(user_id: str):
    users_container = get_container(COSMOS_CONTAINER_USERS)
    institutions_container = get_container(COSMOS_CONTAINER_INSTITUTIONS)
    institutions = []
    
    try:
        user = users_container.read_item(user_id, partition_key=user_id)
        for inst_id in user.get("institutions", []):
            try:
                institution = institutions_container.read_item(inst_id, partition_key=inst_id)
                institutions.append({
                    "id": institution["id"],
                    "name": institution.get("name", "")
                })
            except Exception as e:
                continue
    except Exception as e:
        raise HTTPException(status_code=404, detail="User not found")
    
    return {"institutions": institutions}

@router.post("/user-groups/", dependencies=[Security(get_current_user)])
async def create_user_group(user_group: UserGroup):
    container = get_container(COSMOS_CONTAINER_USER_GROUPS)
    user_group.id = str(uuid.uuid4())
    now = datetime.now(UTC)
    user_group.created_at = now.isoformat()
    user_group.updated_at = now.isoformat()
    container.create_item(body=user_group.model_dump())
    return {"message": "User group created successfully."}

@router.post("/user-groups/with-permissions")
async def create_user_group_with_permissions(group: UserGroupCreate):
    user_groups_container = get_container(COSMOS_CONTAINER_USER_GROUPS)
    menu_container = get_container(COSMOS_CONTAINER_MENU)
    # 1. Create user group entry
    now = datetime.now(UTC).isoformat()
    group_doc = {
        "id": group.id,
        "name": group.name,
        "tag": group.tag,
        "description": group.description,
        "created_at": now,
        "updated_at": now,
    }

    try:
        user_groups_container.create_item(group_doc)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error creating user group: {str(e)}")

    # 2. Fetch menu document (only one menu doc exists)
    menu_items = list(menu_container.read_all_items())
    if not menu_items:
        raise HTTPException(status_code=404, detail="Menu document not found")

    menu_doc = menu_items[0]  # single menu
    updated = False

    # 3. Update allowed_roles in menu/submenus
    for menu in menu_doc["menu"]:
        if menu["id"] in group.menu_items:
            if group.tag not in menu["allowed_roles"]:
                menu["allowed_roles"].append(group.tag)
                updated = True

        for submenu in menu.get("sub_menu", []):
            if submenu["id"] in group.menu_items:
                if group.tag not in submenu["allowed_roles"]:
                    submenu["allowed_roles"].append(group.tag)
                    updated = True

    # 4. Save updated menu document
    if updated:
        menu_doc["updated_at"] = now
        menu_container.upsert_item(menu_doc)

    return group_doc

@router.get("/user-groups/", dependencies=[Security(get_current_user)])
async def get_user_groups(current_user: dict = Depends(get_current_user)):
    container = get_container(COSMOS_CONTAINER_USER_GROUPS)
    query = "SELECT * FROM c"
    items = list(container.query_items(query=query, enable_cross_partition_query=True))
    return items

@router.get("/institutional-user-groups/{institution_id}", dependencies=[Security(get_current_user)])
async def get_institutional_user_groups(institution_id: str, current_user: dict = Depends(get_current_user)):
    institutions_container = get_container(COSMOS_CONTAINER_INSTITUTIONS)
    user_groups_container = get_container(COSMOS_CONTAINER_USER_GROUPS)
    user_roles = get_user_roles(current_user)
    institution = institutions_container.read_item(institution_id, partition_key=institution_id)
    if not institution:
        raise HTTPException(status_code=404, detail="Institution not found")
    
    user_groups = []
    for user_group_id in institution.get("user_groups", []):
        user_group = user_groups_container.read_item(user_group_id, partition_key=user_group_id)

        # Skip appending if tag is SystemAdmin
        if "SystemAdmin" not in user_roles and user_group.get("tag") == "SystemAdmin":
            continue  

        user_groups.append(user_group)

    return {"user_groups": user_groups}

@router.delete("/user-groups/{user_group_id}", dependencies=[Security(get_current_user)])
async def delete_user_group(user_group_id: str):
    container = get_container(COSMOS_CONTAINER_USER_GROUPS)
    container.delete_item(item=user_group_id, partition_key=user_group_id)
    return {"message": "User group deleted successfully."}

@router.get("/count/", dependencies=[Security(get_current_user)])
async def get_count():
    users_container = get_container(COSMOS_CONTAINER_USERS)
    institutions_container = get_container(COSMOS_CONTAINER_INSTITUTIONS)
    user_groups_container = get_container(COSMOS_CONTAINER_USER_GROUPS)
    
    try:        
        users_count = len(list(users_container.read_all_items()))
        institutions_count = len(list(institutions_container.read_all_items()))
        user_groups_count = len(list(user_groups_container.read_all_items()))
        return {
            "count": {
                "users": users_count,
                "institutions": institutions_count,
                "user_groups": user_groups_count
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting counts: {str(e)}")
