import sqlite3
import os
from pathlib import Path
from typing import List, Optional
import uuid
from datetime import datetime
from mod_analyzer.mod.descriptor import Mod
from mod_analyzer.mod.mod_list import ModList
class CK3ModExporter:
    def __init__(self, game_data_path: str, export_beta: bool = False):
        """
        Initialize the exporter
        
        Args:
            game_data_path: Path to the game's data directory (where the .db file lives)
            export_beta: Whether to use beta database path
        """
        self.game_data_path = Path(game_data_path)
        self.export_beta = export_beta
        self.db_path = self._get_db_path()
        
    def _get_db_path(self) -> Path:
        """Get the database file path"""
        db_name = "launcher-v2_openbeta.sqlite" if self.export_beta else "launcher-v2.sqlite"
        return self.game_data_path / db_name
    
    def _ensure_db_exists(self):
        """Ensure the database file exists"""
        if not self.db_path. exists():
            # You'll need an empty template database
            # Copy from a template or create minimal structure
            self._create_minimal_db()
    
    def _create_minimal_db(self):
        """Create a minimal database structure"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # This is a simplified version - adjust based on game version
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS playsets (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                isActive INTEGER DEFAULT 0,
                loadOrder TEXT,
                createdOn TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS mods (
                id TEXT PRIMARY KEY,
                gameRegistryId TEXT,
                status TEXT,
                dirPath TEXT,
                archivePath TEXT,
                displayName TEXT,
                thumbnailPath TEXT,
                thumbnailUrl TEXT,
                source TEXT,
                tags TEXT,
                requiredVersion TEXT,
                shortDescription TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS playsets_mods (
                playsetId TEXT,
                modId TEXT,
                position INTEGER,
                enabled INTEGER DEFAULT 1,
                PRIMARY KEY (playsetId, modId),
                FOREIGN KEY (playsetId) REFERENCES playsets(id),
                FOREIGN KEY (modId) REFERENCES mods(id)
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def _detect_version(self) -> str:
        """Detect database schema version"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT name FROM knoxMigrations")
            migrations = [row[0] for row in cursor.fetchall()]
            
            if "20240109104900_AddOptionalAndRequiredDownload.sql" in migrations:
                return "v5"
            elif "20230830120000_AddCreatedOnColumnToPlaysets.sql" in migrations:
                return "v4"
            elif "20230404120000_AddCreatedOnColumnToPlaysets.sql" in migrations:
                return "v3"
            else:
                return "v2"
        except sqlite3.OperationalError:
            return "v2"
        finally: 
            conn.close()
    
    def export_mods(self, 
                    playset_name: str,
                    mod_list: ModList,
                    enabled_only: bool = False,
                    append_only: bool = False):
        """
        Export mods to the database
        
        Args: 
            playset_name: Name of the playset/collection
            enabled_mods: List of enabled Mod objects
            other_mods: List of other (disabled) Mod objects
            append_only: If True, don't delete existing data
        """
        self._ensure_db_exists()
        conn = sqlite3.connect(self. db_path)
        cursor = conn.cursor()
        
        try:
            # Start transaction
            cursor.execute("BEGIN TRANSACTION")
            
            # Create or get playset
            playset_id = self._create_or_update_playset(
                cursor, playset_name, append_only
            )
            
            # Process mods
            enabled_mods = mod_list.enabled
            all_mods = enabled_mods if enabled_only else list(mod_list.values())
            mod_ids = self._sync_mods(cursor, all_mods, append_only)
            
            # Link mods to playset
            self._sync_playset_mods(
                cursor, playset_id, enabled_mods, mod_ids, append_only
            )
            
            conn.commit()
            
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn. close()
    
    def _create_or_update_playset(self, cursor, name: str, append_only: bool) -> str:
        """Create or update a playset"""
        
        # Deactivate other playsets
        cursor.execute(
            "UPDATE playsets SET isActive = 0 WHERE name != ? ",
            (name,)
        )
        
        # Check if playset exists
        cursor. execute(
            "SELECT id FROM playsets WHERE name = ?",
            (name,)
        )
        row = cursor.fetchone()
        
        if row:
            playset_id = row[0]
            cursor.execute(
                "UPDATE playsets SET isActive = 1 WHERE id = ?",
                (playset_id,)
            )
        else:
            playset_id = str(uuid.uuid4())
            cursor.execute(
                """INSERT INTO playsets (id, name, isActive, loadOrder, createdOn)
                   VALUES (?, ?, 1, 'custom', ?)""",
                (playset_id, name, datetime.now().isoformat())
            )
        
        if not append_only:
            # Delete old playset_mods entries
            cursor.execute(
                "DELETE FROM playsets_mods WHERE playsetId = ?",
                (playset_id,)
            )
        
        return playset_id
    
    def _sync_mods(self, cursor, mods: list[Mod], remove_invalid: bool) -> dict:
        """Sync mod entries and return mapping of fileName -> modId"""
        
        # Get existing mods
        cursor.execute("SELECT id, dirPath, gameRegistryId FROM mods")
        existing_mods = {
            (row[1], row[2]): row[0] 
            for row in cursor.fetchall()
        }
        
        mod_id_map = {}
        
        for mod in mods:
            file_name = mod.path.as_posix()
            descriptor = mod.file.as_posix() if mod.file else ''
            
            # Check if mod exists
            existing_key = (file_name, descriptor)
            
            if existing_key in existing_mods:
                mod_id = existing_mods[existing_key]
                # Update existing mod
                self._update_mod(cursor, mod_id, mod)
            else:
                # Insert new mod
                mod_id = str(uuid.uuid4())
                self._insert_mod(cursor, mod_id, mod)
            
            mod_id_map[file_name] = mod_id
        
        return mod_id_map
    
    def _insert_mod(self, cursor, mod_id: str, mod: Mod):
        """Insert a new mod entry"""
        file_name = str(mod.path).replace('\\', '/')
        descriptor = str(mod.file).replace('\\', '/') if mod.file else ''
        source = 'pdx' if mod.remote_file_id else 'local'

        cursor.execute(
            """INSERT INTO mods (
                id, gameRegistryId, status, dirPath, displayName, source
            ) VALUES (?, ?, ?, ?, ?, ?)""",
            (
                mod_id,
                descriptor,
                'ready_to_play',
                file_name,
                mod.name,
                source
            )
        )
    
    def _update_mod(self, cursor, mod_id: str, mod: Mod):
        """Update an existing mod entry"""
        source = 'steam' if mod.remote_file_id else 'local'
        cursor.execute(
            """UPDATE mods SET 
                displayName = ?,
                status = ?,
                source = ? 
               WHERE id = ?""",
            (
                mod.name,
                'ready_to_play',
                source,
                mod_id
            )
        )
    
    def _sync_playset_mods(self, cursor, playset_id: str, 
                          enabled_mods:  List[Mod], 
                          mod_id_map: dict,
                          append_only: bool):
        """Sync the playset_mods junction table"""
        
        position = 0
        for mod in enabled_mods:
            file_name = str(mod.path).replace('\\', '/')
            mod_id = mod_id_map. get(file_name)
            
            if mod_id: 
                cursor.execute(
                    """INSERT OR REPLACE INTO playsets_mods 
                       (playsetId, modId, position, enabled)
                       VALUES (?, ?, ?, 1)""",
                    (playset_id, mod_id, position)
                )
                position += 1


