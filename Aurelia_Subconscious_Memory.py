import json
import logging
import shutil
import time
from pathlib import Path
from typing import Dict, List, Optional
from filelock import FileLock, Timeout

# Configure logging for the memory module
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [HIPPOCAMPUS] - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

class SubconsciousMemoryManager:
    """
    Manages the Tier 1 (Working Memory) and Tier 2 (State Ledger) 
    for the Qwen 13B Subconscious Agent.
    """
    
    def __init__(self, workspace_path: str | Path):
        self.workspace = Path(workspace_path)
        self.ledger_path = self.workspace / "agent_state_ledger.json"
        self.lock_path = self.workspace / "agent_state_ledger.json.lock"
        
        # --- THE FIX: SINGLETON RE-ENTRANT LOCK ---
        # Instantiating the lock once at the class level prevents self-blocking
        # during complex read-modify-write transactions.
        self.ledger_lock = FileLock(self.lock_path, timeout=5)
        
        # Tier 1: In-RAM Scratchpads (Goal-Specific to prevent cross-contamination)
        self.working_memory_scratchpads: Dict[str, List[Dict[str, str]]] = {}
        self.failure_counts: Dict[str, int] = {}
        
        # Initialize Tier 2 Ledger if it doesn't exist
        self._initialize_ledger()

    # ==========================================
    # NO-LOCK INTERNAL HELPERS (PREVENTS DEADLOCK)
    # ==========================================
    def _initialize_ledger_nolock(self) -> None:
        """Creates the JSON ledger if it doesn't exist, safely, without acquiring a new lock."""
        if not self.ledger_path.exists():
            default_state = {
                "_metadata": {
                    "description": "Aurelia Agent Tool Infrastructure State",
                    "last_updated": "System Initialization"
                },
                "tools": {},
                "pending_goals": []
            }
            self._write_ledger_nolock(default_state)
            logger.info("Initialized fresh agent_state_ledger.json.")

    def _read_ledger_nolock(self) -> Optional[dict]:
        """Reads the ledger natively. Assumes the calling function already holds the self.ledger_lock."""
        try:
            with open(self.ledger_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError:
            logger.error("Ledger JSON corrupted! Backing up and resetting.")
            backup_path = self.workspace / "agent_state_ledger_corrupted.json"
            shutil.copy(self.ledger_path, backup_path)
            self._initialize_ledger_nolock()
            with open(self.ledger_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            return None

    def _write_ledger_nolock(self, data: dict) -> None:
        """Writes to the ledger natively. Assumes the calling function already holds the self.ledger_lock."""
        with open(self.ledger_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)

    def _update_tool_state_nolock(self, tool_name: str, status: str, known_bugs: str, last_outcome: str) -> None:
        """Updates tool state natively. Assumes the calling function already holds the self.ledger_lock."""
        ledger = self._read_ledger_nolock()
        
        if ledger is None:
            ledger = {"tools": {}, "pending_goals": []}
            
        ledger.setdefault("tools", {})
        ledger["tools"][tool_name] = {
            "status": status,
            "known_bugs": known_bugs,
            "last_outcome": last_outcome
        }
        
        self._write_ledger_nolock(ledger)
        logger.info(f"Ledger Updated: {tool_name} is now '{status}'. Outcome logged.")

    def _age_goals_nolock(self) -> None:
        """Ages goals natively. Assumes the calling function already holds the self.ledger_lock."""
        state = self._read_ledger_nolock()
        if state is None:
            return
            
        current_time = time.time()
        updated = False
        
        for goal in state.get("pending_goals", []):
            goal_time = goal.get("timestamp", current_time)
            time_in_queue = current_time - goal_time
            
            bonus = int(time_in_queue // 300)
            
            # --- FIX: Prevent Exponential Priority Compounding ---
            # Lock in the base priority on the first pass
            if "base_priority" not in goal:
                goal["base_priority"] = goal.get("priority", 1)
                updated = True
                
            original_priority = goal["base_priority"]
            
            # --- FIX: Prevent Goal Starvation Downgrade ---
            new_priority = min(10, original_priority + bonus)
            if new_priority != goal.get("priority"):
                goal["priority"] = new_priority
                updated = True
                
        if updated:
            state["pending_goals"] = sorted(
                state["pending_goals"], 
                key=lambda x: x.get("priority", 1), 
                reverse=True
            )
            self._write_ledger_nolock(state)
            logger.info("Goal queue aged and re-prioritized to prevent starvation.")

    # ==========================================
    # THREAD-SAFE PUBLIC METHODS (WITH ZOMBIE BREAKER)
    # ==========================================
    def _initialize_ledger(self) -> None:
        """Public wrapper for safe initialization."""
        retries = 0
        while retries < 10:
            try:
                with self.ledger_lock:
                    self._initialize_ledger_nolock()
                return
            except Timeout:
                retries += 1
                logger.warning(f"Timeout acquiring lock to initialize ledger ({retries}/10). Retrying...")
                time.sleep(0.5)
                
        logger.error("HARD TIMEOUT: Breaking zombie lock file to initialize ledger.")
        if self.lock_path.exists():
            try: self.lock_path.unlink()
            except Exception: pass
        self._initialize_ledger_nolock()

    def _read_ledger(self) -> Optional[dict]:
        """Public wrapper for safe reads."""
        retries = 0
        while retries < 10:
            try:
                with self.ledger_lock:
                    return self._read_ledger_nolock()
            except Timeout:
                retries += 1
                logger.warning(f"Timeout acquiring lock to read ledger ({retries}/10). Retrying to prevent Phantom Drop...")
                time.sleep(0.5)
                
        logger.error("HARD TIMEOUT: Breaking zombie lock file to read ledger.")
        if self.lock_path.exists():
            try: self.lock_path.unlink()
            except Exception: pass
        return self._read_ledger_nolock()

    def _write_ledger(self, data: dict) -> None:
        """Public wrapper for safe writes."""
        retries = 0
        while retries < 10:
            try:
                with self.ledger_lock:
                    self._write_ledger_nolock(data)
                return
            except Timeout:
                retries += 1
                logger.warning(f"Timeout acquiring lock to write ledger ({retries}/10). Retrying to prevent Phantom Drop...")
                time.sleep(0.5)
                
        logger.error("HARD TIMEOUT: Breaking zombie lock file to write ledger.")
        if self.lock_path.exists():
            try: self.lock_path.unlink()
            except Exception: pass
        self._write_ledger_nolock(data)

    def update_tool_state(self, tool_name: str, status: str, known_bugs: str = "None", last_outcome: str = "Pending") -> None:
        """Allows the Orchestrator to update a tool's status and outcome with transactional safety."""
        retries = 0
        while retries < 10:
            try:
                with self.ledger_lock:
                    self._update_tool_state_nolock(tool_name, status, known_bugs, last_outcome)
                return
            except Timeout:
                retries += 1
                logger.warning(f"Timeout acquiring lock to update tool '{tool_name}' ({retries}/10). Retrying to prevent Phantom Drop...")
                time.sleep(0.5)
                
        logger.error(f"HARD TIMEOUT: Breaking zombie lock file to update tool '{tool_name}'.")
        if self.lock_path.exists():
            try: self.lock_path.unlink()
            except Exception: pass
        self._update_tool_state_nolock(tool_name, status, known_bugs, last_outcome)

    def age_goals_in_queue(self) -> None:
        """
        Anti-starvation protocol: Artificially inflates the priority of older goals 
        to prevent perpetual preemption by 80B priority spikes.
        """
        retries = 0
        while retries < 10:
            try:
                with self.ledger_lock:
                    self._age_goals_nolock()
                return
            except Timeout:
                retries += 1
                logger.warning(f"Timeout acquiring lock to age goals ({retries}/10). Retrying...")
                time.sleep(0.5)
                
        logger.error("HARD TIMEOUT: Breaking zombie lock file to age goals.")
        if self.lock_path.exists():
            try: self.lock_path.unlink()
            except Exception: pass
        self._age_goals_nolock()

    # ==========================================
    # TIER 2: LEDGER METHODS (STATE MEMORY)
    # ==========================================

    def get_ledger_state_formatted(self, max_items: int = 10) -> str:
        """Returns the ledger state formatted cleanly for the 13B System Prompt, capped to recent items to prevent context bloat."""
        ledger = self._read_ledger()
        
        if ledger is None:
            return "[CURRENT SYSTEM STATE]: Ledger temporarily inaccessible due to file lock timeout."
            
        tools = ledger.get("tools", {})
        
        if not tools:
            return "[CURRENT SYSTEM STATE]: No tasks or tools currently registered in ledger."
            
        formatted_str = "[CURRENT SYSTEM STATE - RECENT ACHIEVEMENTS & TOOLS]:\n"
        
        recent_items = list(tools.items())[-max_items:]
        
        for tool, state in recent_items:
            formatted_str += f"- {tool} | Status: {state.get('status', 'unknown')} | Known Bugs: {state.get('known_bugs', 'None')} | Last Outcome: {state.get('last_outcome', 'Pending')}\n"
        
        return formatted_str

    # ==========================================
    # TIER 1: SCRATCHPAD METHODS (WORKING MEMORY)
    # ==========================================

    def log_error(self, goal_id: str, step: str, error_traceback: str) -> bool:
        """
        Logs a failed execution attempt to a goal-specific scratchpad.
        Returns True if failure_count > 10 (indicating a Stalled Goal).
        """
        if goal_id not in self.failure_counts:
            self.failure_counts[goal_id] = 0
            self.working_memory_scratchpads[goal_id] = []
            
        self.failure_counts[goal_id] += 1
        
        new_entry = {
            "step": step,
            "error": error_traceback[-1000:] 
        }
        
        if len(self.working_memory_scratchpads[goal_id]) >= 8:
            self.working_memory_scratchpads[goal_id].pop(0)
            
        self.working_memory_scratchpads[goal_id].append(new_entry)
        logger.warning(f"Error logged to scratchpad for goal {goal_id}, step: {step} (Failures: {self.failure_counts[goal_id]})")
        
        return self.failure_counts[goal_id] > 10

    def get_scratchpad_formatted(self, goal_id: str) -> str:
        """Formats the working memory for injection during an Error Reflection loop."""
        scratchpad = self.working_memory_scratchpads.get(goal_id, [])
        if not scratchpad:
            return "" 
            
        formatted_str = "\n[SESSION SCRATCHPAD - PREVIOUS FAILED ATTEMPTS]:\n"
        for i, entry in enumerate(scratchpad, 1):
            formatted_str += f"Attempt {i} ({entry['step']}) Failed with Error:\n{entry['error']}\n---\n"
            
        formatted_str += "[DIRECTIVE]: Analyze the scratchpad errors above inside your <think> tag. Do NOT repeat the exact same code that caused these errors.\n"
        return formatted_str

    def clear_scratchpad(self, goal_id: str) -> None:
        """Wipes the scratchpad for a specific goal upon a successful GOAL_COMPLETED."""
        if goal_id in self.working_memory_scratchpads:
            del self.working_memory_scratchpads[goal_id]
        if goal_id in self.failure_counts:
            del self.failure_counts[goal_id]
        logger.info(f"Scratchpad cleared for goal {goal_id}.")
