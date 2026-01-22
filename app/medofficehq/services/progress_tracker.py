"""
Progress Tracker Service

Tracks progress of rule execution for real-time progress bar updates.
Stores progress in-memory with execution_id as key.

Author: Adil
Date: 2025-01-16
Version: 1.0
"""

import uuid
from datetime import datetime, timezone
from typing import Dict, Optional
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class ExecutionStatus(str, Enum):
    """Execution status"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"


class ProgressTracker:
    """Tracks progress of rule execution"""
    
    def __init__(self):
        """Initialize progress tracker with in-memory storage"""
        self._progress_store: Dict[str, Dict] = {}
        logger.info("ProgressTracker initialized")
    
    def create_execution(self, 
                        total_patients: int,
                        rules: list,
                        project_name: str = "Default Project") -> str:
        """
        Create a new execution tracking entry
        
        Args:
            total_patients: Total number of patients to process
            rules: List of rule numbers to execute (e.g., [21, 22])
            project_name: Project name for this execution
            
        Returns:
            execution_id: Unique identifier for this execution
        """
        execution_id = str(uuid.uuid4())
        
        # Initialize progress for each rule
        rule_progress = {}
        for rule_num in rules:
            rule_progress[str(rule_num)] = {
                "percentage": 0.0,
                "patients_processed": 0,
                "total_patients": total_patients,
                "status": ExecutionStatus.PENDING.value
            }
        
        # Calculate overall progress
        overall_percentage = 0.0
        if rules:
            # Initially, no rule has started
            overall_percentage = 0.0
        
        self._progress_store[execution_id] = {
            "execution_id": execution_id,
            "status": ExecutionStatus.PENDING.value,
            "overall": {
                "percentage": overall_percentage,
                "patients_processed": 0,
                "total_patients": total_patients,
                "current_rule": rules[0] if rules else None,
                "total_rules": len(rules),
                "rules_completed": 0
            },
            "rules": rule_progress,
            "project_name": project_name,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        
        logger.info(f"Created execution tracking: {execution_id} for {total_patients} patients, rules: {rules}")
        return execution_id
    
    def start_execution(self, execution_id: str):
        """Mark execution as started"""
        if execution_id in self._progress_store:
            self._progress_store[execution_id]["status"] = ExecutionStatus.RUNNING.value
            self._progress_store[execution_id]["started_at"] = datetime.now(timezone.utc).isoformat()
            self._update_timestamp(execution_id)
            logger.info(f"Execution {execution_id} started")
    
    def start_rule(self, execution_id: str, rule_number: int):
        """Mark a specific rule as started"""
        if execution_id in self._progress_store:
            rule_key = str(rule_number)
            if rule_key in self._progress_store[execution_id]["rules"]:
                self._progress_store[execution_id]["rules"][rule_key]["status"] = ExecutionStatus.RUNNING.value
                self._progress_store[execution_id]["overall"]["current_rule"] = rule_number
                self._update_timestamp(execution_id)
                logger.info(f"Rule {rule_number} started for execution {execution_id}")
    
    def update_rule_progress(self, 
                            execution_id: str, 
                            rule_number: int, 
                            patients_processed: int):
        """
        Update progress for a specific rule
        
        Args:
            execution_id: Execution ID
            rule_number: Rule number (21 or 22)
            patients_processed: Number of patients processed so far
        """
        if execution_id not in self._progress_store:
            logger.warning(f"Execution {execution_id} not found in progress store")
            return
        
        rule_key = str(rule_number)
        if rule_key not in self._progress_store[execution_id]["rules"]:
            logger.warning(f"Rule {rule_number} not found for execution {execution_id}")
            return
        
        rule_data = self._progress_store[execution_id]["rules"][rule_key]
        total_patients = rule_data["total_patients"]
        
        # Update rule progress
        rule_data["patients_processed"] = patients_processed
        if total_patients > 0:
            rule_data["percentage"] = min((patients_processed / total_patients) * 100, 100.0)
        else:
            rule_data["percentage"] = 0.0
        
        # Update overall progress
        self._update_overall_progress(execution_id)
        self._update_timestamp(execution_id)
    
    def complete_rule(self, execution_id: str, rule_number: int):
        """Mark a specific rule as completed"""
        if execution_id in self._progress_store:
            rule_key = str(rule_number)
            if rule_key in self._progress_store[execution_id]["rules"]:
                rule_data = self._progress_store[execution_id]["rules"][rule_key]
                rule_data["status"] = ExecutionStatus.COMPLETED.value
                rule_data["patients_processed"] = rule_data["total_patients"]
                rule_data["percentage"] = 100.0
                
                # Update overall progress
                self._progress_store[execution_id]["overall"]["rules_completed"] += 1
                self._update_overall_progress(execution_id)
                self._update_timestamp(execution_id)
                logger.info(f"Rule {rule_number} completed for execution {execution_id}")
    
    def complete_execution(self, execution_id: str, success: bool = True):
        """Mark execution as completed"""
        if execution_id in self._progress_store:
            self._progress_store[execution_id]["status"] = ExecutionStatus.COMPLETED.value if success else ExecutionStatus.ERROR.value
            self._progress_store[execution_id]["overall"]["percentage"] = 100.0
            self._progress_store[execution_id]["overall"]["current_rule"] = None
            self._update_timestamp(execution_id)
            logger.info(f"Execution {execution_id} completed (success: {success})")
    
    def set_execution_error(self, execution_id: str, error_message: str):
        """Mark execution as error"""
        if execution_id in self._progress_store:
            self._progress_store[execution_id]["status"] = ExecutionStatus.ERROR.value
            self._progress_store[execution_id]["error_message"] = error_message
            self._update_timestamp(execution_id)
            logger.error(f"Execution {execution_id} error: {error_message}")
    
    def get_progress(self, execution_id: str) -> Optional[Dict]:
        """
        Get current progress for an execution
        
        Args:
            execution_id: Execution ID
            
        Returns:
            Progress dictionary or None if not found
        """
        if execution_id not in self._progress_store:
            return None
        
        progress = self._progress_store[execution_id].copy()
        
        # Format response for API
        response = {
            "execution_id": progress["execution_id"],
            "status": progress["status"],
            "overall": progress["overall"].copy(),
            "rule_21": progress["rules"].get("21", {
                "percentage": 0.0,
                "patients_processed": 0,
                "total_patients": 0,
                "status": ExecutionStatus.PENDING.value
            }),
            "rule_22": progress["rules"].get("22", {
                "percentage": 0.0,
                "patients_processed": 0,
                "total_patients": 0,
                "status": ExecutionStatus.PENDING.value
            }),
            "started_at": progress["started_at"],
            "updated_at": progress["updated_at"]
        }
        
        # Add error message if present
        if "error_message" in progress:
            response["error_message"] = progress["error_message"]
        
        return response
    
    def _update_overall_progress(self, execution_id: str):
        """Update overall progress based on individual rule progress"""
        if execution_id not in self._progress_store:
            return
        
        progress = self._progress_store[execution_id]
        rules = progress["rules"]
        overall = progress["overall"]
        
        # Calculate overall percentage
        total_rules = overall["total_rules"]
        if total_rules == 0:
            overall["percentage"] = 0.0
            return
        
        # Sum up percentages from all rules
        total_percentage = sum(rule_data["percentage"] for rule_data in rules.values())
        overall["percentage"] = total_percentage / total_rules
        
        # Calculate total patients processed
        total_processed = sum(rule_data["patients_processed"] for rule_data in rules.values())
        overall["patients_processed"] = total_processed
    
    def _update_timestamp(self, execution_id: str):
        """Update the updated_at timestamp"""
        if execution_id in self._progress_store:
            self._progress_store[execution_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    def cleanup_old_executions(self, max_age_hours: int = 24):
        """
        Clean up old execution data (older than max_age_hours)
        
        Args:
            max_age_hours: Maximum age in hours before cleanup (default: 24)
        """
        cutoff_time = datetime.now(timezone.utc).timestamp() - (max_age_hours * 3600)
        to_remove = []
        
        for execution_id, progress in self._progress_store.items():
            updated_at = datetime.fromisoformat(progress["updated_at"].replace('Z', '+00:00'))
            if updated_at.timestamp() < cutoff_time:
                to_remove.append(execution_id)
        
        for execution_id in to_remove:
            del self._progress_store[execution_id]
            logger.info(f"Cleaned up old execution: {execution_id}")
        
        if to_remove:
            logger.info(f"Cleaned up {len(to_remove)} old execution(s)")


# Global instance
progress_tracker = ProgressTracker()

