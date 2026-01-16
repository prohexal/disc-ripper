#!/opt/homebrew/bin/python3.11
"""
Disc Ripper GUI - Rip Blu-ray/DVD discs and encode to AV1
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext, simpledialog
import subprocess
import json
import os
import re
import threading
import urllib.request
import urllib.parse
import shutil
import time
import keyring
from io import BytesIO
from pathlib import Path
from typing import List, Dict, Optional, Tuple
try:
    from PIL import Image, ImageTk
except ImportError:
    Image = None
    ImageTk = None

# Set app name for macOS menu bar
try:
    from Foundation import NSBundle
    bundle = NSBundle.mainBundle()
    if bundle:
        info = bundle.localizedInfoDictionary() or bundle.infoDictionary()
        if info:
            info['CFBundleName'] = 'Disc Ripper'
except ImportError:
    pass


class DiscRipperGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Disc Ripper - AV1 Encoder")
        self.root.geometry("900x700")
        
        # Track running processes for cleanup
        self.running_processes = []
        
        # Setup menu bar
        self.setup_menu()
        
        self.makemkv_path = self.find_makemkv()
        self.ffmpeg_path = self.find_ffmpeg()
        self.ffprobe_path = self.find_ffprobe()

        # Load persisted settings early so UI defaults can reflect them
        self.settings = self.load_settings()
        self.disc_info = None
        self.selected_title = None
        self.audio_tracks = []
        self.subtitle_tracks = []
        self.cover_art_label = None
        self.current_movie_data = None
        
        self.setup_ui()
        self.check_dependencies()
        
        # Register cleanup on window close
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        # Check for MakeMKV on first run
        if not self.makemkv_path:
            self.prompt_makemkv_install()
    
    def on_closing(self):
        """Clean up processes and close the application"""
        # Kill any running processes
        for process in self.running_processes:
            try:
                if process.poll() is None:  # Process is still running
                    process.terminate()
                    process.wait(timeout=2)
            except:
                try:
                    process.kill()  # Force kill if terminate fails
                except:
                    pass
        
        # Destroy the window
        self.root.destroy()
    
    def find_makemkv(self) -> Optional[str]:
        """Find MakeMKV command line tool"""
        possible_paths = [
            "/Applications/MakeMKV.app/Contents/MacOS/makemkvcon",
            "/usr/local/bin/makemkvcon",
            "makemkvcon"
        ]
        for path in possible_paths:
            try:
                # Try a simple command to check if makemkvcon exists and runs
                result = subprocess.run([path], 
                                      capture_output=True, timeout=5)
                # makemkvcon returns non-zero for no args, but that's OK - it means it exists
                output = result.stdout.decode() + result.stderr.decode()
                if "makemkv" in output.lower() or "command" in output.lower():
                    return path
            except FileNotFoundError:
                continue
            except:
                # If it exists but times out or errors, that's still OK
                if Path(path).exists():
                    return path
        return None
    
    def find_ffmpeg(self) -> Optional[str]:
        """Find FFmpeg binary"""
        # Try 'which' first (works when running from terminal)
        try:
            result = subprocess.run(["which", "ffmpeg"],
                                  capture_output=True, text=True)
            if result.returncode == 0:
                return result.stdout.strip()
        except:
            pass
        # Fallback: check common Homebrew/macOS paths (important for .app bundles)
        possible_paths = [
            "/opt/homebrew/bin/ffmpeg",
            "/usr/local/bin/ffmpeg",
            "/usr/bin/ffmpeg",
            "ffmpeg"
        ]
        for path in possible_paths:
            if Path(path).exists():
                return path
        return None

    def find_ffprobe(self) -> Optional[str]:
        """Find FFprobe binary (usually shipped with FFmpeg)"""
        # Try 'which' first (works when running from terminal)
        try:
            result = subprocess.run(["which", "ffprobe"],
                                  capture_output=True, text=True)
            if result.returncode == 0:
                return result.stdout.strip()
        except:
            pass
        # Fallback: check common Homebrew/macOS paths (important for .app bundles)
        possible_paths = [
            "/opt/homebrew/bin/ffprobe",
            "/usr/local/bin/ffprobe",
            "/usr/bin/ffprobe",
            "ffprobe"
        ]
        for path in possible_paths:
            if Path(path).exists():
                return path
        return None
    
    def setup_menu(self):
        """Set up menu bar"""
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        
        # Settings menu
        settings_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Settings", menu=settings_menu)
        settings_menu.add_command(label="TMDb API Key", command=self.show_api_key_dialog)
        settings_menu.add_command(label="Plex Settings", command=self.show_plex_settings_dialog)
        settings_menu.add_separator()
        settings_menu.add_command(label="Check for MakeMKV", command=self.check_makemkv_install)

    def get_app_support_dir(self) -> Path:
        """Return app support directory for storing non-secret settings."""
        return Path.home() / "Library" / "Application Support" / "DiscRipper"

    def get_settings_path(self) -> Path:
        return self.get_app_support_dir() / "settings.json"

    def get_default_settings(self) -> Dict:
        return {
            "plex_movies_1080p_path": "",
            "plex_movies_4k_path": "",
            "plex_folder_per_movie": True,
            "plex_auto_copy_after_encode": False,
            "plex_delete_local_after_copy": True,
            "plex_collision_policy": "skip",  # skip | overwrite
            # Optional SMB auto-mount info. Password is stored in Keychain.
            "plex_smb_url": "",  # e.g. smb://SERVER/Share
            "plex_smb_username": "",
            "plex_smb_use_keychain_password": False,
            "plex_smb_auto_mount_on_copy": False
        }

    def load_settings(self) -> Dict:
        """Load settings from disk; secrets are kept in Keychain."""
        settings = self.get_default_settings()
        path = self.get_settings_path()
        try:
            if path.exists():
                data = json.loads(path.read_text())
                if isinstance(data, dict):
                    settings.update(data)
        except Exception as e:
            # Never crash on settings load
            try:
                self.log(f"Warning: failed to load settings: {e}")
            except Exception:
                pass
        return settings

    def save_settings(self):
        """Persist current settings to disk (non-secret values only)."""
        path = self.get_settings_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Only store JSON-serializable settings
            path.write_text(json.dumps(self.settings, indent=2, sort_keys=True))
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save settings: {e}")

    def get_plex_smb_password(self) -> Optional[str]:
        try:
            return keyring.get_password("disc-ripper", "plex_smb_password")
        except Exception:
            return None

    def set_plex_smb_password(self, password: str):
        try:
            if password:
                keyring.set_password("disc-ripper", "plex_smb_password", password)
            else:
                keyring.delete_password("disc-ripper", "plex_smb_password")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save SMB password: {e}")

    def show_plex_settings_dialog(self):
        """Configure Plex copy destinations and optional SMB mount settings."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Plex Settings")
        dialog.geometry("700x520")
        dialog.transient(self.root)
        dialog.grab_set()

        container = ttk.Frame(dialog)
        container.pack(fill=tk.BOTH, expand=True, padx=15, pady=15)

        def browse_folder(var: tk.StringVar):
            folder = filedialog.askdirectory()
            if folder:
                var.set(folder)

        # Destinations
        dest_frame = ttk.LabelFrame(container, text="Destination folders (mounted paths)", padding=10)
        dest_frame.pack(fill=tk.X)

        movies_1080_var = tk.StringVar(value=self.settings.get("plex_movies_1080p_path", ""))
        movies_4k_var = tk.StringVar(value=self.settings.get("plex_movies_4k_path", ""))

        ttk.Label(dest_frame, text="Movies (1080p and below):").grid(row=0, column=0, sticky="w")
        ttk.Entry(dest_frame, textvariable=movies_1080_var, width=60).grid(row=0, column=1, padx=5, pady=4, sticky="ew")
        ttk.Button(dest_frame, text="Browse", command=lambda: browse_folder(movies_1080_var)).grid(row=0, column=2)

        ttk.Label(dest_frame, text="4K Movies (2160p):").grid(row=1, column=0, sticky="w")
        ttk.Entry(dest_frame, textvariable=movies_4k_var, width=60).grid(row=1, column=1, padx=5, pady=4, sticky="ew")
        ttk.Button(dest_frame, text="Browse", command=lambda: browse_folder(movies_4k_var)).grid(row=1, column=2)

        dest_frame.columnconfigure(1, weight=1)

        # Behavior
        behavior_frame = ttk.LabelFrame(container, text="Behavior", padding=10)
        behavior_frame.pack(fill=tk.X, pady=(12, 0))

        folder_per_movie_var = tk.BooleanVar(value=bool(self.settings.get("plex_folder_per_movie", True)))
        auto_copy_var = tk.BooleanVar(value=bool(self.settings.get("plex_auto_copy_after_encode", False)))
        delete_local_var = tk.BooleanVar(value=bool(self.settings.get("plex_delete_local_after_copy", True)))

        ttk.Checkbutton(behavior_frame, text="Create folder per movie", variable=folder_per_movie_var).pack(anchor="w")
        ttk.Checkbutton(behavior_frame, text="Auto-copy to Plex after encode", variable=auto_copy_var).pack(anchor="w")
        ttk.Checkbutton(behavior_frame, text="Delete local output after successful copy", variable=delete_local_var).pack(anchor="w")

        collision_frame = ttk.Frame(behavior_frame)
        collision_frame.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(collision_frame, text="If destination file exists:").pack(side=tk.LEFT)
        collision_var = tk.StringVar(value=self.settings.get("plex_collision_policy", "skip"))
        collision_menu = ttk.Combobox(collision_frame, textvariable=collision_var, state="readonly", width=12,
                                      values=["skip", "overwrite"])
        collision_menu.pack(side=tk.LEFT, padx=8)

        # Optional SMB mount
        smb_frame = ttk.LabelFrame(container, text="Optional: SMB auto-mount (only attempted during copy)", padding=10)
        smb_frame.pack(fill=tk.X, pady=(12, 0))

        smb_url_var = tk.StringVar(value=self.settings.get("plex_smb_url", ""))
        smb_user_var = tk.StringVar(value=self.settings.get("plex_smb_username", ""))
        smb_use_keychain_var = tk.BooleanVar(value=bool(self.settings.get("plex_smb_use_keychain_password", False)))
        smb_auto_mount_var = tk.BooleanVar(value=bool(self.settings.get("plex_smb_auto_mount_on_copy", False)))

        ttk.Label(smb_frame, text="SMB URL (e.g. smb://unraid/Media):").grid(row=0, column=0, sticky="w")
        ttk.Entry(smb_frame, textvariable=smb_url_var, width=60).grid(row=0, column=1, padx=5, pady=4, sticky="ew")

        ttk.Label(smb_frame, text="Username:").grid(row=1, column=0, sticky="w")
        ttk.Entry(smb_frame, textvariable=smb_user_var, width=30).grid(row=1, column=1, padx=5, pady=4, sticky="w")

        ttk.Checkbutton(smb_frame, text="Use Keychain-stored password", variable=smb_use_keychain_var).grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Checkbutton(smb_frame, text="Auto-mount SMB share when copying", variable=smb_auto_mount_var).grid(row=3, column=0, columnspan=2, sticky="w")

        # Password entry (only used to set keychain)
        pw_frame = ttk.Frame(smb_frame)
        pw_frame.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Label(pw_frame, text="Password (stored in Keychain on Save):").pack(side=tk.LEFT)
        smb_pw_var = tk.StringVar(value="")
        ttk.Entry(pw_frame, textvariable=smb_pw_var, show="*", width=30).pack(side=tk.LEFT, padx=8)

        smb_frame.columnconfigure(1, weight=1)

        # Buttons
        button_frame = ttk.Frame(container)
        button_frame.pack(fill=tk.X, pady=(18, 0))

        def save_and_close():
            self.settings["plex_movies_1080p_path"] = movies_1080_var.get().strip()
            self.settings["plex_movies_4k_path"] = movies_4k_var.get().strip()
            self.settings["plex_folder_per_movie"] = bool(folder_per_movie_var.get())
            self.settings["plex_auto_copy_after_encode"] = bool(auto_copy_var.get())
            self.settings["plex_delete_local_after_copy"] = bool(delete_local_var.get())
            self.settings["plex_collision_policy"] = collision_var.get()

            self.settings["plex_smb_url"] = smb_url_var.get().strip()
            self.settings["plex_smb_username"] = smb_user_var.get().strip()
            self.settings["plex_smb_use_keychain_password"] = bool(smb_use_keychain_var.get())
            self.settings["plex_smb_auto_mount_on_copy"] = bool(smb_auto_mount_var.get())

            # Only set keychain password if user provided one.
            pw = smb_pw_var.get()
            if pw:
                self.set_plex_smb_password(pw)
                self.settings["plex_smb_use_keychain_password"] = True

            self.save_settings()
            dialog.destroy()

        ttk.Button(button_frame, text="Save", command=save_and_close).pack(side=tk.RIGHT, padx=5)
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(side=tk.RIGHT, padx=5)
    
    def get_tmdb_api_key(self) -> Optional[str]:
        """Get TMDb API key from secure keychain storage"""
        try:
            api_key = keyring.get_password("disc-ripper", "tmdb_api_key")
            return api_key
        except Exception as e:
            return None
    
    def set_tmdb_api_key(self, api_key: str):
        """Store TMDb API key securely in keychain"""
        try:
            if api_key:
                keyring.set_password("disc-ripper", "tmdb_api_key", api_key)
            else:
                keyring.delete_password("disc-ripper", "tmdb_api_key")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save API key: {e}")
    
    def show_api_key_dialog(self):
        """Show dialog for entering TMDb API key"""
        dialog = tk.Toplevel(self.root)
        dialog.title("TMDb API Key")
        dialog.geometry("500x300")
        dialog.transient(self.root)
        dialog.grab_set()
        
        # Instructions
        instructions = tk.Label(dialog, text="Enter your TMDb API key to enable automatic movie metadata and cover art.\n\n"
                                          "Get a free API key at: https://www.themoviedb.org/settings/api",
                               justify=tk.LEFT, wraplength=450)
        instructions.pack(padx=20, pady=20)
        
        # Current key (masked)
        current_key = self.get_tmdb_api_key()
        current_label = tk.Label(dialog, text=f"Current: {'*' * 20 if current_key else 'Not set'}")
        current_label.pack()
        
        # Input frame
        input_frame = ttk.Frame(dialog)
        input_frame.pack(padx=20, pady=10, fill=tk.X)
        
        ttk.Label(input_frame, text="API Key:").pack(side=tk.LEFT, padx=5)
        api_key_var = tk.StringVar(value=current_key or "")
        api_key_entry = ttk.Entry(input_frame, textvariable=api_key_var, width=50, show="*")
        api_key_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        
        # Show/Hide toggle
        def toggle_visibility():
            if api_key_entry.cget("show") == "*":
                api_key_entry.config(show="")
                show_btn.config(text="Hide")
            else:
                api_key_entry.config(show="*")
                show_btn.config(text="Show")
        
        show_btn = ttk.Button(input_frame, text="Show", command=toggle_visibility, width=6)
        show_btn.pack(side=tk.LEFT, padx=5)
        
        # Buttons
        button_frame = ttk.Frame(dialog)
        button_frame.pack(pady=20)
        
        def save_and_close():
            self.set_tmdb_api_key(api_key_var.get().strip())
            messagebox.showinfo("Saved", "TMDb API key saved securely!")
            dialog.destroy()
        
        def clear_and_close():
            self.set_tmdb_api_key("")
            messagebox.showinfo("Cleared", "TMDb API key removed")
            dialog.destroy()
        
        ttk.Button(button_frame, text="Save", command=save_and_close).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Clear", command=clear_and_close).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(side=tk.LEFT, padx=5)
    
    def prompt_makemkv_install(self):
        """Prompt user to install MakeMKV"""
        response = messagebox.askyesno(
            "MakeMKV Not Found",
            "MakeMKV is required to rip discs.\n\n"
            "Would you like to download and install it now?\n\n"
            "(This will open the MakeMKV download page)"
        )
        if response:
            import webbrowser
            webbrowser.open("https://www.makemkv.com/download/")
            messagebox.showinfo(
                "Installation",
                "After installing MakeMKV, restart this application.\n\n"
                "Or use Settings → Check for MakeMKV to verify installation."
            )
    
    def check_makemkv_install(self):
        """Check if MakeMKV is installed and update path"""
        self.makemkv_path = self.find_makemkv()
        if self.makemkv_path:
            messagebox.showinfo("Found", f"MakeMKV found:\n{self.makemkv_path}")
        else:
            response = messagebox.askyesno(
                "Not Found",
                "MakeMKV is not installed.\n\nWould you like to download it?"
            )
            if response:
                import webbrowser
                webbrowser.open("https://www.makemkv.com/download/")
    
    def check_dependencies(self):
        """Check if required tools are installed"""
        messages = []
        if not self.makemkv_path:
            messages.append("❌ MakeMKV not found - Use Settings menu to install")
        else:
            messages.append(f"✓ MakeMKV found: {self.makemkv_path}")
        
        if not self.ffmpeg_path:
            messages.append("❌ FFmpeg not found - Install with: brew install ffmpeg")
        else:
            messages.append(f"✓ FFmpeg found: {self.ffmpeg_path}")

        if not getattr(self, 'ffprobe_path', None):
            messages.append("⚠️  FFprobe not found - resolution detection for Plex routing may be limited")
        else:
            messages.append(f"✓ FFprobe found: {self.ffprobe_path}")
        
        if self.get_tmdb_api_key():
            messages.append("✓ TMDb API configured")
        else:
            messages.append("⚠️  TMDb API not configured - Use Settings menu to add")
        
        self.log("\n".join(messages))
    
    def setup_ui(self):
        """Setup the user interface"""
        # Main notebook for tabs
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Tab 1: Disc Detection & Title Selection
        self.disc_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.disc_frame, text="1. Detect Disc")
        self.setup_disc_tab()
        
        # Tab 2: Encoding Options
        self.encode_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.encode_frame, text="2. Encoding Options")
        self.setup_encode_tab()
        
        # Tab 3: Output & Progress
        self.output_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.output_frame, text="3. Progress")
        self.setup_output_tab()

        # Tab 4: Plex Sync
        self.plex_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.plex_frame, text="4. Plex Sync")
        self.setup_plex_sync_tab()
        
    def setup_disc_tab(self):
        """Setup disc detection and title selection tab"""
        # Scan disc button
        scan_frame = ttk.LabelFrame(self.disc_frame, text="Disc Detection", padding=10)
        scan_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Button(scan_frame, text="Scan for Disc", 
                  command=self.scan_disc).pack(side=tk.LEFT, padx=5)
        ttk.Label(scan_frame, text="Drive:").pack(side=tk.LEFT, padx=5)
        self.drive_var = tk.StringVar(value="0")
        ttk.Entry(scan_frame, textvariable=self.drive_var, width=5).pack(side=tk.LEFT)
        
        # Title list
        title_frame = ttk.LabelFrame(self.disc_frame, text="Available Titles", padding=10)
        title_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        self.title_tree = ttk.Treeview(title_frame, 
                                       columns=("Duration", "Size", "Chapters", "Tracks"),
                                       show="tree headings", height=10)
        self.title_tree.heading("#0", text="Title")
        self.title_tree.heading("Duration", text="Duration")
        self.title_tree.heading("Size", text="Size")
        self.title_tree.heading("Chapters", text="Chapters")
        self.title_tree.heading("Tracks", text="Audio/Subtitle Tracks")
        
        self.title_tree.column("#0", width=100)
        self.title_tree.column("Duration", width=100)
        self.title_tree.column("Size", width=100)
        self.title_tree.column("Chapters", width=80)
        self.title_tree.column("Tracks", width=150)
        
        scrollbar = ttk.Scrollbar(title_frame, orient=tk.VERTICAL, 
                                 command=self.title_tree.yview)
        self.title_tree.configure(yscrollcommand=scrollbar.set)
        
        self.title_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.title_tree.bind("<<TreeviewSelect>>", self.on_title_select)
        
        # Select title button
        ttk.Button(self.disc_frame, text="Select Title & Continue", 
                  command=self.select_title).pack(pady=10)
    
    def setup_encode_tab(self):
        """Setup encoding options tab"""
        # Movie name and cover art
        top_frame = ttk.Frame(self.encode_frame)
        top_frame.pack(fill=tk.X, padx=10, pady=10)
        
        # Left side: Cover art
        cover_frame = ttk.LabelFrame(top_frame, text="Cover Art", padding=5)
        cover_frame.pack(side=tk.LEFT, padx=(0, 10))
        
        self.cover_art_label = ttk.Label(cover_frame, text="No cover")
        self.cover_art_label.pack()
        
        # Right side: Movie details
        details_frame = ttk.Frame(top_frame)
        details_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        name_frame = ttk.LabelFrame(details_frame, text="Movie Name", padding=10)
        name_frame.pack(fill=tk.X)
        
        ttk.Label(name_frame, text="Name:").pack(side=tk.LEFT, padx=5)
        self.movie_name_var = tk.StringVar(value="Movie")
        ttk.Entry(name_frame, textvariable=self.movie_name_var, width=40).pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        ttk.Button(name_frame, text="Search TMDb", command=self.search_movie).pack(side=tk.LEFT, padx=5)
        
        # Output folder
        folder_frame = ttk.LabelFrame(self.encode_frame, text="Output Folder", padding=10)
        folder_frame.pack(fill=tk.X, padx=10, pady=10)
        
        self.output_folder_var = tk.StringVar(value=str(Path.home() / "Movies" / "Ripped"))
        ttk.Entry(folder_frame, textvariable=self.output_folder_var, width=50).pack(side=tk.LEFT, padx=5)
        ttk.Button(folder_frame, text="Browse", 
                  command=self.browse_output).pack(side=tk.LEFT, padx=5)
        
        # Video encoding mode
        video_frame = ttk.LabelFrame(details_frame, text="Video Encoding", padding=10)
        video_frame.pack(fill=tk.X, pady=(10, 0))
        
        self.video_mode_var = tk.StringVar(value="auto")
        ttk.Radiobutton(video_frame, text="Auto (detect HDR/DV)", 
                       variable=self.video_mode_var, value="auto").pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(video_frame, text="Copy (preserve original)", 
                       variable=self.video_mode_var, value="copy").pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(video_frame, text="Encode to AV1", 
                       variable=self.video_mode_var, value="encode").pack(side=tk.LEFT, padx=10)
        
        # Quality preset
        quality_frame = ttk.LabelFrame(self.encode_frame, text="Quality Preset", padding=10)
        quality_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Label(quality_frame, text="Preset:").pack(side=tk.LEFT, padx=5)
        self.quality_preset_var = tk.StringVar(value="balanced")
        quality_presets = [
            ("Maximum (AV1, Slow, Smallest)", "maximum"),
            ("High (AV1, Medium, Small)", "high"),
            ("Balanced (AV1, Medium, Good)", "balanced"),
            ("Fast (AV1, Fast, Larger)", "fast"),
            ("Hardware (H.265, Very Fast)", "hardware")
        ]
        preset_menu = ttk.Combobox(quality_frame, textvariable=self.quality_preset_var, 
                                  values=[p[1] for p in quality_presets], state="readonly", width=30)
        preset_menu.pack(side=tk.LEFT, padx=5)
        
        # Bind to show description
        def show_preset_info(event=None):
            preset = self.quality_preset_var.get()
            descriptions = {
                "maximum": "AV1 Preset 4, CRF 20 - Best quality, ~4hr for 2hr movie",
                "high": "AV1 Preset 6, CRF 25 - Excellent quality, ~2.5hr for 2hr movie",
                "balanced": "AV1 Preset 8, CRF 30 - Very good quality, ~1.5hr for 2hr movie",
                "fast": "AV1 Preset 10, CRF 35 - Good quality, ~50min for 2hr movie",
                "hardware": "H.265 VideoToolbox - Excellent quality, ~15min for 2hr movie"
            }
            preset_info_label.config(text=descriptions.get(preset, ""))
        
        preset_menu.bind("<<ComboboxSelected>>", show_preset_info)
        
        preset_info_label = ttk.Label(quality_frame, text="", foreground="gray")
        preset_info_label.pack(side=tk.LEFT, padx=10)
        show_preset_info()  # Show initial description
        
        # Resolution
        res_frame = ttk.LabelFrame(self.encode_frame, text="Resolution", padding=10)
        res_frame.pack(fill=tk.X, padx=10, pady=10)
        
        self.resolution_var = tk.StringVar(value="original")
        resolutions = [("Original", "original"), ("4K (2160p)", "2160"), 
                      ("1080p", "1080"), ("720p", "720"), ("480p", "480")]
        for text, value in resolutions:
            ttk.Radiobutton(res_frame, text=text, variable=self.resolution_var, 
                          value=value).pack(side=tk.LEFT, padx=10)
        
        # Audio tracks
        audio_frame = ttk.LabelFrame(self.encode_frame, text="Audio Tracks", padding=10)
        audio_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        self.audio_listbox = tk.Listbox(audio_frame, selectmode=tk.MULTIPLE, height=4, exportselection=False)
        self.audio_listbox.pack(fill=tk.BOTH, expand=True)
        
        # Subtitle tracks
        subtitle_frame = ttk.LabelFrame(self.encode_frame, text="Subtitle Tracks", padding=10)
        subtitle_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        self.subtitle_listbox = tk.Listbox(subtitle_frame, selectmode=tk.MULTIPLE, height=4, exportselection=False)
        self.subtitle_listbox.pack(fill=tk.BOTH, expand=True)
        
        # Chapters
        chapter_frame = ttk.LabelFrame(self.encode_frame, text="Chapters", padding=10)
        chapter_frame.pack(fill=tk.X, padx=10, pady=10)
        
        self.include_chapters_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(chapter_frame, text="Include chapter markers", 
                       variable=self.include_chapters_var).pack()
        
        # Ripped file status
        self.ripped_status_frame = ttk.LabelFrame(self.encode_frame, text="Ripped File Status", padding=10)
        self.ripped_status_frame.pack(fill=tk.X, padx=10, pady=10)
        
        self.ripped_status_label = ttk.Label(self.ripped_status_frame, text="No ripped file found", foreground="gray")
        self.ripped_status_label.pack()
        
        # Buttons frame
        buttons_frame = ttk.Frame(self.encode_frame)
        buttons_frame.pack(pady=20)
        
        # Start encoding (rip + encode)
        ttk.Button(buttons_frame, text="Rip & Encode", 
                  command=self.start_encoding, style="Accent.TButton").pack(side=tk.LEFT, padx=5)
        
        # Re-encode only button
        self.reencode_button = ttk.Button(buttons_frame, text="Re-encode Only (Skip Rip)", 
                                         command=self.start_reencoding, state="disabled")
        self.reencode_button.pack(side=tk.LEFT, padx=5)
        
        # Check for existing ripped file on tab change
        self.notebook.bind("<<NotebookTabChanged>>", lambda e: self.check_ripped_file())
    
    def setup_output_tab(self):
        """Setup output and progress tab"""
        # Progress bar
        progress_frame = ttk.LabelFrame(self.output_frame, text="Progress", padding=10)
        progress_frame.pack(fill=tk.X, padx=10, pady=10)
        
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(progress_frame, variable=self.progress_var,
                                           maximum=100)
        self.progress_bar.pack(fill=tk.X, pady=5)
        
        # Progress label with percentage
        self.progress_label = ttk.Label(progress_frame, text="Ready - 0%", font=('', 10))
        self.progress_label.pack()
        
        # Log output with collapse/expand
        log_header_frame = ttk.Frame(self.output_frame)
        log_header_frame.pack(fill=tk.X, padx=10, pady=(10, 0))
        
        ttk.Label(log_header_frame, text="Log", font=('', 10, 'bold')).pack(side=tk.LEFT, padx=5)
        
        self.log_expanded = tk.BooleanVar(value=True)
        self.log_toggle_button = ttk.Button(log_header_frame, text="Hide",
                                           command=self.toggle_log, width=10)
        self.log_toggle_button.pack(side=tk.RIGHT, padx=5)
        
        # Log frame that can be hidden
        self.log_frame = ttk.Frame(self.output_frame)
        self.log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        
        self.log_text = scrolledtext.ScrolledText(self.log_frame, height=20, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def setup_plex_sync_tab(self):
        """Setup Plex Sync tab for batch copying local outputs to Plex."""
        top = ttk.Frame(self.plex_frame)
        top.pack(fill=tk.X, padx=10, pady=10)

        ttk.Label(top, text="Pending files (local outputs not yet copied)", font=('', 11, 'bold')).pack(side=tk.LEFT)

        ttk.Button(top, text="Refresh", command=self.refresh_plex_queue).pack(side=tk.RIGHT, padx=5)
        ttk.Button(top, text="Copy Selected to Plex", command=self.copy_selected_to_plex).pack(side=tk.RIGHT, padx=5)

        tree_frame = ttk.Frame(self.plex_frame)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        self.plex_queue_tree = ttk.Treeview(tree_frame, columns=("Size", "Resolution", "Destination"), show="tree headings", selectmode="extended")
        self.plex_queue_tree.heading("#0", text="File")
        self.plex_queue_tree.heading("Size", text="Size")
        self.plex_queue_tree.heading("Resolution", text="Resolution")
        self.plex_queue_tree.heading("Destination", text="Destination")

        self.plex_queue_tree.column("#0", width=360)
        self.plex_queue_tree.column("Size", width=100)
        self.plex_queue_tree.column("Resolution", width=110)
        self.plex_queue_tree.column("Destination", width=140)

        yscroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.plex_queue_tree.yview)
        self.plex_queue_tree.configure(yscrollcommand=yscroll.set)

        self.plex_queue_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        yscroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.plex_queue_paths = {}

        # Initial load
        self.refresh_plex_queue()
    
    def toggle_log(self):
        """Toggle log visibility"""
        if self.log_expanded.get():
            # Hide log
            self.log_frame.pack_forget()
            self.log_toggle_button.config(text="Show")
            self.log_expanded.set(False)
        else:
            # Show log
            self.log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
            self.log_toggle_button.config(text="Hide")
            self.log_expanded.set(True)
    
    def log(self, message: str):
        """Add message to log"""
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.root.update_idletasks()

    def format_bytes(self, num_bytes: int) -> str:
        if num_bytes is None:
            return ""
        size = float(num_bytes)
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size < 1024.0:
                return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} {unit}"
            size /= 1024.0
        return f"{size:.1f} PB"

    def sanitize_path_component(self, name: str) -> str:
        """Sanitize a movie name for use as a folder/file name."""
        if not name:
            return "Movie"
        # Replace path separators and other problematic characters.
        name = name.replace("/", "-").replace("\\", "-")
        name = re.sub(r'[:\n\r\t]+', ' ', name)
        name = re.sub(r'\s+', ' ', name).strip()
        return name

    def get_video_dimensions(self, video_file: Path) -> Tuple[Optional[int], Optional[int]]:
        """Return (width, height) for the first video stream."""
        if not video_file or not video_file.exists():
            return (None, None)

        # Prefer ffprobe.
        if getattr(self, 'ffprobe_path', None):
            try:
                cmd = [
                    self.ffprobe_path, "-v", "error",
                    "-select_streams", "v:0",
                    "-show_entries", "stream=width,height",
                    "-of", "json",
                    str(video_file)
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
                if result.returncode == 0:
                    data = json.loads(result.stdout)
                    streams = data.get("streams") or []
                    if streams:
                        w = streams[0].get("width")
                        h = streams[0].get("height")
                        return (int(w) if w else None, int(h) if h else None)
            except Exception:
                pass

        # Fallback: parse ffmpeg -i output.
        try:
            if self.ffmpeg_path:
                cmd = [self.ffmpeg_path, "-i", str(video_file), "-hide_banner"]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
                out = result.stderr or ""
                # Find first Video stream line containing 1234x567
                for line in out.split("\n"):
                    if "Video:" in line:
                        m = re.search(r'(\d{3,5})x(\d{3,5})', line)
                        if m:
                            return (int(m.group(1)), int(m.group(2)))
        except Exception:
            pass

        return (None, None)

    def is_4k_by_dimensions(self, width: Optional[int], height: Optional[int]) -> bool:
        if width is None or height is None:
            return False
        return height >= 2000 or width >= 3800

    def ensure_smb_mounted_if_needed(self) -> None:
        """Optionally mount the SMB share only when performing a copy.

        We never mount on startup; this is only attempted if the user enabled it.
        """
        if not self.settings.get("plex_smb_auto_mount_on_copy"):
            return

        smb_url = (self.settings.get("plex_smb_url") or "").strip()
        username = (self.settings.get("plex_smb_username") or "").strip()
        use_pw = bool(self.settings.get("plex_smb_use_keychain_password"))
        if not smb_url:
            return

        # If at least one destination exists, don't force mount.
        p1080_s = (self.settings.get("plex_movies_1080p_path") or "").strip()
        p4k_s = (self.settings.get("plex_movies_4k_path") or "").strip()
        p1080 = Path(p1080_s) if p1080_s else None
        p4k = Path(p4k_s) if p4k_s else None
        if (p1080 and p1080.exists()) or (p4k and p4k.exists()):
            return

        self.log(f"Plex destination not mounted. Attempting SMB mount for: {smb_url}")

        try:
            if use_pw and username:
                pw = self.get_plex_smb_password() or ""
                if not pw:
                    self.log("SMB password not available in Keychain; cannot auto-mount")
                    return
                # Use AppleScript to mount with credentials.
                script = f'mount volume "{smb_url}" as user name "{username}" with password "{pw}"'
                subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=30)
            else:
                # Let macOS/Keychain handle credentials (may prompt if not saved).
                subprocess.run(["open", smb_url], capture_output=True, text=True, timeout=30)
        except Exception as e:
            self.log(f"SMB mount attempt failed: {e}")
            return

        # Give Finder a moment to mount.
        time.sleep(2)

    def get_plex_destination_root_for_file(self, video_file: Path) -> Tuple[Optional[Path], str]:
        """Return (dest_root, label) based on output resolution."""
        p1080_s = (self.settings.get("plex_movies_1080p_path") or "").strip()
        p4k_s = (self.settings.get("plex_movies_4k_path") or "").strip()
        p1080 = Path(p1080_s) if p1080_s else None
        p4k = Path(p4k_s) if p4k_s else None

        w, h = self.get_video_dimensions(video_file)
        if self.is_4k_by_dimensions(w, h):
            return (p4k, "4K Movies")
        return (p1080, "Movies")

    def build_plex_destination_path(self, dest_root: Path, movie_name: str) -> Path:
        safe_name = self.sanitize_path_component(movie_name)
        if self.settings.get("plex_folder_per_movie", True):
            return dest_root / safe_name / f"{safe_name}.mkv"
        return dest_root / f"{safe_name}.mkv"

    def copy_with_progress(self, src: Path, dst: Path, overall_base: float, overall_span: float, overwrite: bool) -> str:
        """Copy src -> dst with chunked progress.

        Returns: "copied" | "skipped"
        """
        if dst.exists() and not overwrite:
            return "skipped"

        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_suffix(dst.suffix + ".partial")

        total = src.stat().st_size
        copied = 0
        last_ui = 0.0

        if tmp.exists():
            try:
                tmp.unlink()
            except Exception:
                pass

        with open(src, "rb") as fsrc, open(tmp, "wb") as fdst:
            while True:
                buf = fsrc.read(8 * 1024 * 1024)  # 8MB chunks
                if not buf:
                    break
                fdst.write(buf)
                copied += len(buf)

                now = time.time()
                if now - last_ui > 0.25:
                    pct = (copied / total) * 100 if total else 100
                    overall = overall_base + (pct / 100.0) * overall_span
                    self.progress_var.set(overall)
                    self.progress_label.config(text=f"Copying to Plex - {int(overall)}%")
                    self.root.update_idletasks()
                    last_ui = now

        # Verify size at minimum
        if tmp.stat().st_size != total:
            try:
                tmp.unlink()
            except Exception:
                pass
            raise Exception("Copy verification failed (size mismatch)")

        # Atomic replace to final path
        os.replace(tmp, dst)
        return "copied"

    def copy_file_to_plex(self, local_file: Path, overall_base: float = 0.0, overall_span: float = 100.0) -> Tuple[bool, Optional[Path]]:
        """Copy a local encoded file into the appropriate Plex destination.

        Returns (success, destination_path).
        If collision policy is skip and destination exists, returns (False, destination_path).
        """
        if not local_file.exists():
            raise Exception(f"Local file not found: {local_file}")

        movie_name = local_file.stem

        # Try to mount share only if user opted in.
        self.ensure_smb_mounted_if_needed()

        dest_root, dest_label = self.get_plex_destination_root_for_file(local_file)
        if not dest_root or not str(dest_root):
            raise Exception("Plex destination folders not configured. Use Settings → Plex Settings.")

        if not dest_root.exists():
            raise Exception(f"Plex destination not available: {dest_root}")

        dest_path = self.build_plex_destination_path(dest_root, movie_name)
        overwrite = (self.settings.get("plex_collision_policy") == "overwrite")

        if dest_path.exists() and not overwrite:
            self.log(f"Skip: destination exists ({dest_label}): {dest_path}")
            return (False, dest_path)

        self.log(f"Copying to Plex ({dest_label}): {dest_path}")
        result = self.copy_with_progress(local_file, dest_path, overall_base, overall_span, overwrite=overwrite)
        if result == "skipped":
            self.log(f"Skip: destination exists: {dest_path}")
            return (False, dest_path)

        self.log(f"Copied OK: {dest_path}")

        # Optionally delete local file after copy
        if self.settings.get("plex_delete_local_after_copy", True):
            try:
                local_file.unlink()
                self.log(f"Deleted local output: {local_file.name}")
            except Exception as e:
                self.log(f"Warning: failed to delete local output: {e}")

        return (True, dest_path)

    def refresh_plex_queue(self):
        """Scan local output folder for MKVs that haven't been copied yet (still present locally)."""
        # Clear
        for child in self.plex_queue_tree.get_children():
            self.plex_queue_tree.delete(child)
        self.plex_queue_paths = {}

        output_dir = Path(self.output_folder_var.get()) if hasattr(self, 'output_folder_var') else None
        if not output_dir or not output_dir.exists():
            return

        mkvs = sorted([p for p in output_dir.glob("*.mkv") if p.is_file()])
        for idx, f in enumerate(mkvs):
            size = f.stat().st_size
            w, h = self.get_video_dimensions(f)
            res = f"{w}x{h}" if w and h else "Unknown"
            _, dest_label = self.get_plex_destination_root_for_file(f)

            iid = str(idx)
            self.plex_queue_tree.insert("", tk.END, iid=iid, text=f.name,
                                        values=(self.format_bytes(size), res, dest_label))
            self.plex_queue_paths[iid] = str(f)

    def copy_selected_to_plex(self):
        selected = list(self.plex_queue_tree.selection())
        if not selected:
            messagebox.showinfo("Plex Sync", "Select one or more files to copy.")
            return

        files = [Path(self.plex_queue_paths[i]) for i in selected if i in self.plex_queue_paths]
        total_bytes = sum((f.stat().st_size for f in files if f.exists()), 0)

        if not messagebox.askyesno(
            "Confirm",
            f"Copy {len(files)} file(s) to Plex?\nTotal size: {self.format_bytes(total_bytes)}\n\nFiles will be deleted locally after successful copy (if enabled in Plex Settings)."
        ):
            return

        def worker():
            try:
                for i, f in enumerate(files):
                    # Use 0-100 progress per file in the batch.
                    self.progress_var.set(0)
                    self.progress_label.config(text="Copying to Plex - 0%")
                    self.copy_file_to_plex(f, overall_base=0.0, overall_span=100.0)
                self.log("Plex batch copy complete.")
            except Exception as e:
                self.log(f"Plex batch copy error: {e}")
            finally:
                self.refresh_plex_queue()

        threading.Thread(target=worker, daemon=True).start()
    
    def scan_disc(self):
        """Scan for disc using MakeMKV"""
        if not self.makemkv_path:
            messagebox.showerror("Error", "MakeMKV not found!")
            return
        
        # Prevent multiple simultaneous scans
        if hasattr(self, '_scanning') and self._scanning:
            self.log("Scan already in progress, please wait...")
            return
        
        self._scanning = True
        self.log("Scanning disc (this may take 2-3 minutes for Blu-ray)...")
        self.progress_label.config(text="Scanning disc...")
        
        def scan_thread():
            try:
                drive = self.drive_var.get()
                cmd = [self.makemkv_path, "-r", "info", f"disc:{drive}"]
                # Increase timeout to 180 seconds (3 minutes) for Blu-ray discs
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
                
                if result.returncode != 0:
                    self.log(f"Error scanning disc: {result.stderr}")
                    self.progress_label.config(text="Scan failed")
                    self._scanning = False
                    return
                
                self.parse_disc_info(result.stdout)
                
                # Log a brief summary so we can debug discs where stream parsing differs
                try:
                    titles_count = len(getattr(self, 'disc_info', {}) or {})
                    tracks_count = len(getattr(self, 'tracks_info', {}) or {})
                    self.log(f"Scan summary: {titles_count} titles, stream info for {tracks_count} titles")
                except Exception:
                    pass
                
                self.log("Disc scan complete!")
                self.progress_label.config(text="Scan complete")
            except subprocess.TimeoutExpired:
                self.log("Error: Scan timed out after 3 minutes. Check disc or try again.")
                self.progress_label.config(text="Scan timeout")
            except Exception as e:
                self.log(f"Error: {str(e)}")
                self.progress_label.config(text="Scan failed")
            finally:
                self._scanning = False
        
        threading.Thread(target=scan_thread, daemon=True).start()
    
    def _parse_makemkv_value(self, raw: str) -> str:
        """Parse MakeMKV 'rest' field.

        MakeMKV often formats fields as: 0,"Some Value". We want the actual string value.
        """
        if raw is None:
            return ""
        raw = raw.strip()
        # Prefer quoted payload if present.
        m = re.search(r'"(.*?)"', raw)
        if m:
            return m.group(1).strip()
        # Fallback: take the last comma-delimited token.
        if "," in raw:
            return raw.split(",")[-1].strip().strip('"')
        return raw.strip().strip('"')

    def parse_disc_info(self, output: str):
        """Parse MakeMKV output to extract title information"""
        self.title_tree.delete(*self.title_tree.get_children())
        
        lines = output.split("\n")
        titles = {}
        tracks = {}  # Store audio/subtitle track info by title
        
        for line in lines:
            # Title line: TINFO:0,9,0,"Title name"
            if line.startswith("TINFO:"):
                parts = line.split(",", 3)
                if len(parts) >= 4:
                    title_id = parts[0].split(":")[1]
                    attr_id = parts[1]
                    value = self._parse_makemkv_value(parts[3])
                    
                    if title_id not in titles:
                        titles[title_id] = {}
                    
                    # Map attribute IDs
                    if attr_id == "9":  # Duration
                        titles[title_id]["duration"] = value
                    elif attr_id == "10":  # Chapters
                        titles[title_id]["chapters"] = value
                    elif attr_id == "11":  # Size
                        titles[title_id]["size"] = value
                    elif attr_id == "2":  # Name
                        titles[title_id]["name"] = value
            
            # Stream info: SINFO:title,stream,attr,value
            elif line.startswith("SINFO:"):
                parts = line.split(",", 3)
                if len(parts) >= 4:
                    title_id = parts[0].split(":")[1]
                    stream_id = parts[1]
                    attr_id = parts[2]
                    value = self._parse_makemkv_value(parts[3])
                    
                    if title_id not in tracks:
                        tracks[title_id] = {}
                    if stream_id not in tracks[title_id]:
                        tracks[title_id][stream_id] = {}
                    
                    # Stream attributes - MakeMKV SINFO codes
                    # See: https://forum.makemkv.com/forum/viewtopic.php?f=10&t=4385
                    if attr_id == "1":  # Stream type
                        tracks[title_id][stream_id]["type"] = value
                    elif attr_id == "2":  # Track name/description
                        tracks[title_id][stream_id]["name"] = value
                    elif attr_id == "3":  # Stream codec short name
                        tracks[title_id][stream_id]["codec_short"] = value
                    elif attr_id == "4":  # Stream codec long name
                        tracks[title_id][stream_id]["codec"] = value
                    elif attr_id == "5":  # Stream codec ID
                        tracks[title_id][stream_id]["codec_id"] = value
                    elif attr_id == "6":  # Stream codec profile
                        tracks[title_id][stream_id]["codec_profile"] = value
                    elif attr_id == "7":  # Stream language name
                        tracks[title_id][stream_id]["language"] = value
                    elif attr_id == "19":  # Stream flags
                        tracks[title_id][stream_id]["flags"] = value
                    elif attr_id == "20":  # Language code (ISO 639-2)
                        tracks[title_id][stream_id]["lang_code"] = value
                    elif attr_id == "22":  # Language name (English)
                        tracks[title_id][stream_id]["lang_eng"] = value
                    elif attr_id == "30":  # Tree info
                        tracks[title_id][stream_id]["tree_info"] = value
                    elif attr_id == "31":  # Panels count
                        tracks[title_id][stream_id]["panels"] = value
                    elif attr_id == "32":  # MKV flags
                        tracks[title_id][stream_id]["mkv_flags"] = value
                    elif attr_id == "33":  # Metadata language code
                        tracks[title_id][stream_id]["metadata_lang"] = value
                    elif attr_id == "38":  # Output file name
                        tracks[title_id][stream_id]["output_name"] = value
                    elif attr_id == "40":  # Original ID
                        tracks[title_id][stream_id]["orig_id"] = value
                    elif attr_id == "41":  # Segment map
                        tracks[title_id][stream_id]["segment_map"] = value
                    elif attr_id == "42":  # Output format
                        tracks[title_id][stream_id]["output_format"] = value
        
        # Populate tree
        for title_id, info in titles.items():
            duration = info.get("duration", "Unknown")
            size = info.get("size", "Unknown")
            chapters = info.get("chapters", "0")
            name = info.get("name", f"Title {title_id}")
            
            self.title_tree.insert("", tk.END, iid=title_id,
                                  text=name,
                                  values=(duration, size, chapters, ""))
        
        self.disc_info = titles
        self.tracks_info = tracks
    
    def on_title_select(self, event):
        """Handle title selection"""
        selection = self.title_tree.selection()
        if selection:
            self.selected_title = selection[0]
    
    def select_title(self):
        """Continue to encoding options with selected title"""
        if not self.selected_title:
            messagebox.showwarning("Warning", "Please select a title first")
            return
        
        self.log(f"Selected title: {self.selected_title}")
        
        # Populate audio and subtitle tracks for selected title
        self.populate_tracks()
        
        # Auto-search for movie name using disc name
        if self.disc_info and self.selected_title in self.disc_info:
            disc_name = self.disc_info[self.selected_title].get("name", "")
            if disc_name and disc_name != f"Title {self.selected_title}":
                self.movie_name_var.set(disc_name)
                # Auto-search TMDb
                threading.Thread(target=self.auto_search_movie, args=(disc_name,), daemon=True).start()
        
        # Switch to encoding tab
        self.notebook.select(self.encode_frame)
    
    def format_language(self, language: str, lang_code: str = "") -> str:
        """Format language name nicely"""
        # Map common language codes to full names
        lang_map = {
            "eng": "English",
            "spa": "Spanish",
            "fra": "French",
            "deu": "German",
            "ita": "Italian",
            "jpn": "Japanese",
            "kor": "Korean",
            "chi": "Chinese",
            "rus": "Russian",
            "por": "Portuguese",
            "ara": "Arabic",
            "hin": "Hindi",
            "dut": "Dutch",
            "pol": "Polish",
            "tur": "Turkish",
            "hun": "Hungarian",
            "ces": "Czech",
            "swe": "Swedish",
            "dan": "Danish",
            "nor": "Norwegian",
            "fin": "Finnish"
        }
        
        # Try language code first
        if lang_code and lang_code.lower() in lang_map:
            return lang_map[lang_code.lower()]
        
        # Try language name
        if language and language.lower() in lang_map:
            return lang_map[language.lower()]
        
        # Return as-is if not found
        return language if language and language != "Unknown" else lang_code if lang_code else "Unknown"
    
    def format_codec(self, codec: str) -> str:
        """Format codec name nicely"""
        # Map codec names to friendly names
        codec_map = {
            "truehd": "Dolby TrueHD",
            "dts": "DTS",
            "dtshd": "DTS-HD",
            "dts-hd ma": "DTS-HD MA",
            "ac3": "Dolby Digital (AC3)",
            "eac3": "Dolby Digital Plus (E-AC3)",
            "aac": "AAC",
            "mp3": "MP3",
            "pcm": "PCM",
            "flac": "FLAC",
            "pgs": "PGS (Blu-ray Subtitles)",
            "subrip": "SRT (SubRip)",
            "vobsub": "VobSub (DVD Subtitles)",
            "ass": "ASS/SSA"
        }
        
        codec_lower = codec.lower()
        for key, value in codec_map.items():
            if key in codec_lower:
                return value
        
        return codec if codec != "Unknown" else "Unknown"
    
    def populate_tracks(self):
        """Populate audio and subtitle tracks from selected title"""
        self.log("[V2] Populating audio and subtitle tracks with improved formatting...")
        self.audio_listbox.delete(0, tk.END)
        self.subtitle_listbox.delete(0, tk.END)
        self.audio_tracks = []
        self.subtitle_tracks = []
        
        # Check if we have detailed track info from MakeMKV
        has_tracks = (hasattr(self, 'tracks_info') and 
                     self.selected_title in self.tracks_info and 
                     len(self.tracks_info[self.selected_title]) > 0)
        
        self.log(f"Has detailed track info: {has_tracks}")
        if hasattr(self, 'tracks_info'):
            self.log(f"Tracks info keys: {list(self.tracks_info.keys())}")
            if self.selected_title in self.tracks_info:
                self.log(f"Track count for title {self.selected_title}: {len(self.tracks_info[self.selected_title])}")
        
        if has_tracks:
            # Use detailed MakeMKV track info
            title_tracks = self.tracks_info[self.selected_title]
            
            audio_count = 0
            subtitle_count = 0
            
            for stream_id, stream_info in sorted(title_tracks.items(), key=lambda kv: int(kv[0])):
                stream_type = (stream_info.get("type", "") or "").strip()
                codec_long = (stream_info.get("codec", "") or "").strip()
                codec_short = (stream_info.get("codec_short", "") or "").strip()
                language = (stream_info.get("language", "") or "").strip()
                lang_code = (stream_info.get("lang_code", "") or "").strip()
                
                # Prefer short codec if present (e.g. dts, truehd), else long codec name.
                codec = codec_short if codec_short else (codec_long if codec_long else "Unknown")
                language = language if language else "Unknown"
                
                # Debug: Log first few streams
                if int(stream_id) < 5:
                    self.log(f"Stream {stream_id}: type='{stream_type}', codec='{codec}', lang='{language}', code='{lang_code}'")
                
                # Check for audio (case-insensitive)
                if "audio" in stream_type.lower():
                    audio_count += 1
                    # Format language nicely
                    lang_name = self.format_language(language, lang_code)
                    # Format codec nicely
                    codec_name = self.format_codec(codec)
                    label = f"{lang_name} - {codec_name}"
                    self.audio_listbox.insert(tk.END, label)
                    self.audio_tracks.append({"id": stream_id, "language": language, "codec": codec})
                    # Auto-select first audio track
                    if len(self.audio_tracks) == 1:
                        self.audio_listbox.selection_set(0)
                
                # Check for subtitles (case-insensitive)
                elif "subtitle" in stream_type.lower():
                    subtitle_count += 1
                    # Format language nicely
                    lang_name = self.format_language(language, lang_code)
                    # Format codec nicely
                    codec_name = self.format_codec(codec)
                    
                    # Debug: Log first few subtitle streams with all available fields
                    if subtitle_count <= 3:
                        self.log(f"Subtitle {stream_id}: name='{stream_info.get('name', '')}', flags='{stream_info.get('flags', '')}', mkv_flags='{stream_info.get('mkv_flags', '')}', tree_info='{stream_info.get('tree_info', '')}'")
                    
                    # Add subtitle details (forced, commentary, SDH, etc.)
                    details = []
                    
                    # Check tree_info field (this is where MakeMKV puts subtitle descriptions)
                    tree_info = stream_info.get("tree_info", "")
                    if tree_info:
                        tree_info_clean = tree_info.split(',"')[-1].strip('"').strip() if '"' in tree_info else tree_info
                        tree_info_lower = tree_info_clean.lower()
                        
                        # Check for forced subtitles
                        if "forced" in tree_info_lower or "(forced only)" in tree_info_lower:
                            details.append("Foreign Parts Only")
                        # Check for SDH/hearing impaired
                        elif "sdh" in tree_info_lower or "hearing" in tree_info_lower or "cc" in tree_info_lower:
                            details.append("Hearing Impaired")
                        # Check for commentary
                        elif "commentary" in tree_info_lower or "comment" in tree_info_lower:
                            details.append("Commentary")
                    
                    # Fallback: Check track name
                    if not details:
                        track_name = stream_info.get("name", "")
                        if track_name:
                            track_name_clean = track_name.split(',"')[-1].strip('"').strip() if '"' in track_name else track_name
                            # Remove HTML tags
                            track_name_clean = re.sub(r'<[^>]+>', '', track_name_clean).strip()
                            if track_name_clean and track_name_clean.lower() not in ["subtitle", "subtitles", "sub", "track information"]:
                                name_lower = track_name_clean.lower()
                                if "forced" in name_lower:
                                    details.append("Foreign Parts Only")
                                elif "commentary" in name_lower or "comment" in name_lower:
                                    details.append("Commentary")
                                elif "sdh" in name_lower or "hearing" in name_lower or "cc" in name_lower:
                                    details.append("Hearing Impaired")
                                else:
                                    details.append(track_name_clean)
                    
                    # Build label with track number for disambiguation
                    if details:
                        label = f"Track {subtitle_count}: {lang_name} - {codec_name} [{', '.join(details)}]"
                    else:
                        label = f"Track {subtitle_count}: {lang_name} - {codec_name}"
                    
                    self.subtitle_listbox.insert(tk.END, label)
                    self.subtitle_tracks.append({"id": stream_id, "language": language, "codec": codec})
            
            self.log(f"Found {audio_count} audio tracks, {subtitle_count} subtitle tracks")
            
            # Safety net: if parsing produced streams but none matched audio/subtitle,
            # fall back to auto-detection rather than showing empty lists.
            if audio_count == 0:
                self.log("Warning: No audio tracks detected from disc scan; falling back to auto-detect")
                self.audio_listbox.insert(tk.END, "All audio tracks (will be auto-detected)")
                # Do not auto-select; if nothing is selected we map all audio.
                self.audio_tracks = [{"id": "all", "language": "all", "codec": "auto"}]
            if subtitle_count == 0:
                self.log("Warning: No subtitle tracks detected from disc scan; falling back to auto-detect")
                self.subtitle_listbox.insert(tk.END, "All subtitle tracks (will be auto-detected)")
                self.subtitle_tracks = [{"id": "all", "language": "all", "codec": "auto"}]
        else:
            # Fallback: MakeMKV doesn't provide stream details, add generic options
            self.log("Note: Stream details not available from disc scan")
            self.log("Audio and subtitle tracks will be detected from ripped file")
            
            # Add generic placeholder
            self.audio_listbox.insert(tk.END, "All audio tracks (will be auto-detected)")
            # Do not auto-select; if nothing is selected we map all audio.
            self.audio_tracks = [{"id": "all", "language": "all", "codec": "auto"}]
            
            self.subtitle_listbox.insert(tk.END, "All subtitle tracks (will be auto-detected)")
            self.subtitle_tracks = [{"id": "all", "language": "all", "codec": "auto"}]
    
    def analyze_video(self, input_file: Path) -> Dict:
        """Analyze video file for HDR and Dolby Vision metadata"""
        info = {"hdr": False, "dolby_vision": False}
        
        try:
            cmd = [self.ffmpeg_path, "-i", str(input_file), "-hide_banner"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            output = result.stderr  # FFmpeg outputs to stderr
            
            # Check for Dolby Vision
            if "DOVI" in output or "Dolby Vision" in output or "dvcC" in output or "dvvC" in output:
                info["dolby_vision"] = True
                self.log("Dolby Vision detected in source")
            
            # Check for HDR (HDR10, HDR10+, etc.)
            if "SMPTE2084" in output or "smpte2084" in output or "bt2020" in output:
                info["hdr"] = True
                
                # Extract color metadata
                for line in output.split("\n"):
                    if "color_primaries" in line:
                        info["color_primaries"] = "bt2020"
                    if "color_trc" in line and "smpte2084" in line.lower():
                        info["color_trc"] = "smpte2084"
                    if "color_space" in line:
                        info["colorspace"] = "bt2020nc"
                    if "Mastering Display Metadata" in line or "master-display" in line:
                        # Try to extract master display info
                        match = re.search(r'G\(([^)]+)\)', line)
                        if match:
                            info["master_display"] = match.group(1)
                
                self.log("HDR metadata detected in source")
        
        except Exception as e:
            self.log(f"Warning: Could not analyze video metadata: {e}")
        
        return info
    
    def get_audio_info(self, input_file: Path) -> Dict:
        """Get audio codec information from input file"""
        info = {"codecs": []}
        
        try:
            cmd = [self.ffmpeg_path, "-i", str(input_file), "-hide_banner"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            output = result.stderr
            
            # Parse audio streams
            for line in output.split("\n"):
                if "Audio:" in line:
                    # Extract codec name
                    parts = line.split("Audio:")
                    if len(parts) > 1:
                        codec_part = parts[1].split(",")[0].strip().lower()
                        info["codecs"].append(codec_part)
        
        except Exception as e:
            self.log(f"Warning: Could not analyze audio: {e}")
        
        return info
    
    def search_movie(self):
        """Search for movie on TMDb"""
        query = self.movie_name_var.get()
        if not query:
            return
        
        def search_thread():
            try:
                self.auto_search_movie(query, show_dialog=True)
            except Exception as e:
                self.log(f"Error searching movie: {e}")
                messagebox.showerror("Error", f"Failed to search TMDb: {e}")
        
        threading.Thread(target=search_thread, daemon=True).start()
    
    def auto_search_movie(self, query: str, show_dialog: bool = False):
        """Automatically search TMDb for movie"""
        api_key = self.get_tmdb_api_key()
        if not api_key:
            if show_dialog:
                messagebox.showwarning(
                    "TMDb Not Configured",
                    "TMDb API key not set.\n\nGo to Settings → TMDb API Key to configure."
                )
            return
        
        try:
            # Search for movie
            search_url = f"https://api.themoviedb.org/3/search/movie?api_key={api_key}&query={urllib.parse.quote(query)}"
            
            with urllib.request.urlopen(search_url, timeout=10) as response:
                data = json.loads(response.read().decode())
            
            if data.get("results"):
                # Get first result
                movie = data["results"][0]
                self.current_movie_data = movie
                
                # Update movie name
                title = movie.get("title", query)
                year = movie.get("release_date", "")[:4]
                if year:
                    title = f"{title} ({year})"
                
                self.movie_name_var.set(title)
                self.log(f"Found movie: {title}")
                
                # Download and display cover art
                if movie.get("poster_path"):
                    self.download_cover_art(movie["poster_path"])
                
                if show_dialog:
                    messagebox.showinfo("Movie Found", f"Found: {title}")
            else:
                self.log(f"No results found for: {query}")
                if show_dialog:
                    messagebox.showinfo("No Results", f"No movies found for: {query}")
        
        except Exception as e:
            self.log(f"TMDb search error: {e}")
            if show_dialog:
                messagebox.showerror("Error", f"Search failed: {e}")
    
    def download_cover_art(self, poster_path: str):
        """Download and display movie cover art"""
        if not Image or not ImageTk:
            self.log("PIL not installed - cover art disabled")
            return
        
        try:
            # TMDb image base URL
            image_url = f"https://image.tmdb.org/t/p/w200{poster_path}"
            
            with urllib.request.urlopen(image_url, timeout=10) as response:
                image_data = response.read()
            
            # Load and resize image
            image = Image.open(BytesIO(image_data))
            image.thumbnail((150, 225), Image.Resampling.LANCZOS)
            
            # Convert to PhotoImage and display
            photo = ImageTk.PhotoImage(image)
            self.cover_art_label.configure(image=photo, text="")
            self.cover_art_label.image = photo  # Keep a reference
            
            self.log("Cover art loaded")
        
        except Exception as e:
            self.log(f"Failed to load cover art: {e}")
    
    def check_ripped_file(self):
        """Check if a ripped MKV file exists in temp directory"""
        temp_dir = Path.home() / "tmp" / "disc_rip"
        mkv_files = list(temp_dir.glob("*.mkv")) if temp_dir.exists() else []
        
        if mkv_files:
            file = mkv_files[0]
            size_mb = file.stat().st_size / (1024 * 1024)
            self.ripped_status_label.config(
                text=f"✓ Found: {file.name} ({size_mb:.1f} MB)",
                foreground="green"
            )
            self.reencode_button.config(state="normal")
        else:
            self.ripped_status_label.config(
                text="No ripped file found",
                foreground="gray"
            )
            self.reencode_button.config(state="disabled")
    
    def browse_output(self):
        """Browse for output folder"""
        folder = filedialog.askdirectory(initialdir=self.output_folder_var.get())
        if folder:
            self.output_folder_var.set(folder)
    
    def start_encoding(self):
        """Start the ripping and encoding process"""
        if not self.selected_title:
            messagebox.showwarning("Warning", "Please select a title first")
            return
        
        if not self.ffmpeg_path:
            messagebox.showerror("Error", "FFmpeg not found! Install with: brew install ffmpeg")
            return
        
        # Switch to progress tab
        self.notebook.select(self.output_frame)
        
        def encode_thread():
            try:
                self.rip_and_encode(skip_rip=False)
            except Exception as e:
                self.log(f"Error: {str(e)}")
                self.progress_label.config(text="Failed")
        
        threading.Thread(target=encode_thread, daemon=True).start()
    
    def start_reencoding(self):
        """Start encoding without ripping (use existing temp file)"""
        if not self.ffmpeg_path:
            messagebox.showerror("Error", "FFmpeg not found! Install with: brew install ffmpeg")
            return
        
        # Check temp file still exists
        temp_dir = Path.home() / "tmp" / "disc_rip"
        mkv_files = list(temp_dir.glob("*.mkv")) if temp_dir.exists() else []
        
        if not mkv_files:
            messagebox.showerror("Error", "No ripped file found. Please rip the disc first.")
            return
        
        # Switch to progress tab
        self.notebook.select(self.output_frame)
        
        def encode_thread():
            try:
                self.rip_and_encode(skip_rip=True)
            except Exception as e:
                self.log(f"Error: {str(e)}")
                self.progress_label.config(text="Failed")
        
        threading.Thread(target=encode_thread, daemon=True).start()
    
    def rip_and_encode(self, skip_rip=False):
        """Rip disc with MakeMKV and encode to AV1"""
        movie_name = self.movie_name_var.get()
        output_folder = Path(self.output_folder_var.get())
        output_folder.mkdir(parents=True, exist_ok=True)
        
        temp_dir = Path.home() / "tmp" / "disc_rip"
        temp_dir.mkdir(parents=True, exist_ok=True)
        
        if skip_rip:
            # Skip ripping, use existing file
            self.log("Skipping rip, using existing file...")
            mkv_files = list(temp_dir.glob("*.mkv"))
            if not mkv_files:
                raise Exception("No existing MKV file found")
            input_file = mkv_files[0]
            self.log(f"Using existing rip: {input_file}")
            self.progress_var.set(50)
        else:
            # Step 1: Rip with MakeMKV
            self.log("Step 1: Ripping disc with MakeMKV...")
            self.progress_label.config(text="Ripping disc - 10%")
            self.progress_var.set(10)
            
            # Clean up any existing files in temp directory to avoid MakeMKV prompts
            for old_file in temp_dir.glob("*.mkv"):
                try:
                    old_file.unlink()
                    self.log(f"Cleaned up old temp file: {old_file.name}")
                except Exception as e:
                    self.log(f"Warning: Could not delete {old_file.name}: {e}")
            
            drive = self.drive_var.get()
            cmd = [self.makemkv_path, "mkv", f"disc:{drive}", 
                   self.selected_title, str(temp_dir)]
            
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, 
                                      stderr=subprocess.PIPE, text=True)
            self.running_processes.append(process)
            
            for line in process.stdout:
                self.log(line.strip())
                if "Progress" in line:
                    try:
                        progress = int(re.search(r'(\d+)%', line).group(1))
                        overall = int(10 + progress * 0.4)  # 10-50%
                        self.progress_var.set(overall)
                        self.progress_label.config(text=f"Ripping disc - {overall}%")
                    except:
                        pass
            
            process.wait()
            self.running_processes.remove(process)
            
            if process.returncode != 0:
                raise Exception("MakeMKV ripping failed")
            
            # Find the ripped MKV file
            mkv_files = list(temp_dir.glob("*.mkv"))
            if not mkv_files:
                raise Exception("No MKV file found after ripping")
            
            input_file = mkv_files[0]
            self.log(f"Ripped to: {input_file}")
        
        # Analyze input file for HDR/DV metadata
        video_info = self.analyze_video(input_file)
        
        # Step 2: Encode with FFmpeg
        self.log("Step 2: Encoding to AV1...")
        self.progress_label.config(text="Encoding - 50%")
        self.progress_var.set(50)
        
        output_file = output_folder / f"{movie_name}.mkv"

        # Handle existing output file to avoid ffmpeg prompt in .app bundle
        overwrite_output = False
        if output_file.exists():
            overwrite_output = messagebox.askyesno(
                "Output Exists",
                f"Output file already exists:\n{output_file}\n\nOverwrite it?"
            )
            if not overwrite_output:
                self.log(f"Output exists, skipping encode: {output_file}")
                raise Exception("Output file already exists (skipped)")
        
        # Build FFmpeg command
        cmd = [self.ffmpeg_path, "-y" if overwrite_output else "-n", "-i", str(input_file)]
        
        # Map video stream
        cmd.extend(["-map", "0:v:0"])
        
        # Video encoding with HDR/DV preservation
        has_hdr = video_info.get("hdr", False)
        has_dv = video_info.get("dolby_vision", False)
        video_mode = self.video_mode_var.get()
        
        # Determine encoding mode
        use_copy = False
        
        if video_mode == "copy":
            # Force copy mode
            self.log("Video mode: Copy (preserving original)")
            use_copy = True
        elif video_mode == "encode":
            # Force encode mode
            self.log("Video mode: Encode to AV1")
            use_copy = False
        else:  # auto
            # Auto-detect based on content
            if has_dv:
                self.log("Detected Dolby Vision - auto-selecting copy mode")
                use_copy = True
            else:
                use_copy = False
        
        if use_copy:
            cmd.extend(["-c:v", "copy"])
            self.log("Using copy mode - original video preserved")
        else:
            # Get quality preset
            preset = self.quality_preset_var.get()
            preset_config = {
                "maximum": {"encoder": "libsvtav1", "preset": "4", "crf": "20"},
                "high": {"encoder": "libsvtav1", "preset": "6", "crf": "25"},
                "balanced": {"encoder": "libsvtav1", "preset": "8", "crf": "30"},
                "fast": {"encoder": "libsvtav1", "preset": "10", "crf": "35"},
                "hardware": {"encoder": "hevc_videotoolbox", "preset": None, "crf": None}
            }
            
            config = preset_config.get(preset, preset_config["balanced"])
            
            if config["encoder"] == "hevc_videotoolbox":
                # Hardware acceleration with VideoToolbox
                self.log(f"Using Hardware Acceleration (VideoToolbox H.265)")
                cmd.extend(["-c:v", "hevc_videotoolbox", "-q:v", "65"])
                # VideoToolbox quality: 0-100, 65 is good balance
            else:
                # Software AV1 encoding
                if has_hdr:
                    self.log(f"Encoding with {preset} preset (AV1) - HDR metadata preserved")
                else:
                    self.log(f"Encoding with {preset} preset (AV1)")
                
                cmd.extend(["-c:v", config["encoder"], "-preset", config["preset"], "-crf", config["crf"]])
                
                # Preserve HDR metadata for AV1
                if has_hdr:
                    cmd.extend([
                        "-color_primaries", str(video_info.get("color_primaries", "bt2020")),
                        "-color_trc", str(video_info.get("color_trc", "smpte2084")),
                        "-colorspace", str(video_info.get("colorspace", "bt2020nc"))
                    ])
        
        # Resolution (skip if using copy)
        resolution = self.resolution_var.get()
        if resolution != "original" and not use_copy:
            cmd.extend(["-vf", f"scale=-2:{resolution}"])
        
        # Audio - preserve high-quality codecs (DTS, TrueHD, Dolby Digital)
        audio_info = self.get_audio_info(input_file)
        selected_audio = self.audio_listbox.curselection()
        
        if selected_audio:
            # If we couldn't enumerate tracks at scan-time we insert a single placeholder.
            # Treat selecting it as "include all audio".
            if len(getattr(self, 'audio_tracks', [])) == 1 and self.audio_tracks[0].get("id") == "all":
                cmd.extend(["-map", "0:a"])  # Include all audio
            else:
                # Map selected audio streams by index
                for idx in selected_audio:
                    cmd.extend(["-map", f"0:a:{idx}"])
        else:
            cmd.extend(["-map", "0:a"])  # Include all audio
        
        # Determine audio codec strategy
        # Note: audio_info['codecs'] are strings like "dts (dca) (dts-hd ma)"; use substring matching.
        high_quality_codecs = ["dts", "truehd", "eac3", "ac3", "dtshd", "dts-hd"]
        detected_codecs = [c.lower() for c in (audio_info.get("codecs") or [])]
        has_hq_audio = any(any(hq in c for hq in high_quality_codecs) for c in detected_codecs)
        
        if has_hq_audio:
            self.log(f"Detected high-quality audio ({', '.join(audio_info.get('codecs', []))}) - copying")
            cmd.extend(["-c:a", "copy"])  # Preserve original audio
        else:
            self.log("Converting audio to Opus")
            cmd.extend(["-c:a", "libopus", "-b:a", "128k"])
        
        # Subtitles - only include selected tracks
        selected_subs = self.subtitle_listbox.curselection()
        if selected_subs:
            # If we couldn't enumerate tracks at scan-time we insert a single placeholder.
            # Treat selecting it as "include all subtitles".
            if len(getattr(self, 'subtitle_tracks', [])) == 1 and self.subtitle_tracks[0].get("id") == "all":
                cmd.extend(["-map", "0:s?"])  # Include all subtitle streams (optional if none exist)
                cmd.extend(["-c:s", "copy"])
            else:
                # Map each selected subtitle stream individually and ignore if it doesn't exist
                for idx in selected_subs:
                    cmd.extend(["-map", f"0:s:{idx}?"])  # The ? makes it optional
                cmd.extend(["-c:s", "copy"])
        # If no subtitles selected, don't include any
        
        # Output
        cmd.append(str(output_file))
        
        self.log(f"FFmpeg command: {' '.join(cmd)}")
        
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, 
                                  stderr=subprocess.PIPE, text=True)
        self.running_processes.append(process)
        
        duration = None
        for line in process.stderr:
            self.log(line.strip())
            
            # Parse duration
            if "Duration:" in line and not duration:
                match = re.search(r'Duration: (\d{2}):(\d{2}):(\d{2})', line)
                if match:
                    h, m, s = map(int, match.groups())
                    duration = h * 3600 + m * 60 + s
            
            # Parse progress
            if duration and "time=" in line:
                match = re.search(r'time=(\d{2}):(\d{2}):(\d{2})', line)
                if match:
                    h, m, s = map(int, match.groups())
                    current = h * 3600 + m * 60 + s
                    progress = (current / duration) * 100
                    overall = int(50 + progress * 0.45)  # 50-95% (leave room for Plex copy)
                    self.progress_var.set(overall)
                    # Calculate ETA
                    elapsed = current
                    if progress > 0:
                        total_time = (elapsed / progress) * 100
                        remaining = int(total_time - elapsed)
                        eta_min = remaining // 60
                        self.progress_label.config(text=f"Encoding - {overall}% (ETA: {eta_min}min)")
                    else:
                        self.progress_label.config(text=f"Encoding - {overall}%")
        
        process.wait()
        self.running_processes.remove(process)
        
        if process.returncode != 0:
            raise Exception("FFmpeg encoding failed")

        # Verify output was actually created
        if not output_file.exists() or output_file.stat().st_size == 0:
            raise Exception("FFmpeg did not produce an output file")
        
        # Encoding complete (leave headroom for optional Plex copy)
        self.progress_var.set(95)
        self.progress_label.config(text="Encoding complete - 95%")

        plex_dest = None
        if self.settings.get("plex_auto_copy_after_encode"):
            try:
                self.log("Starting Plex copy...")
                ok, dest_path = self.copy_file_to_plex(output_file, overall_base=95.0, overall_span=5.0)
                plex_dest = dest_path
                if ok:
                    self.progress_var.set(100)
                    self.progress_label.config(text="Complete - 100%")
                else:
                    # Skipped due to collision policy
                    self.progress_var.set(95)
                    self.progress_label.config(text="Plex copy skipped - 95%")
            except Exception as e:
                self.log(f"Plex copy failed: {e}")
                self.progress_var.set(95)
                self.progress_label.config(text="Plex copy failed - 95%")
        else:
            self.progress_var.set(100)
            self.progress_label.config(text="Complete - 100%")

        # Success - keep temp file for potential re-encoding
        self.log(f"\n✓ Complete! Output: {output_file}")
        self.log(f"Temp file kept at: {input_file} (for re-encoding with different settings)")

        # Update ripped file status
        self.check_ripped_file()

        if plex_dest:
            messagebox.showinfo("Success", f"Encoding complete!\n\nPlex destination: {plex_dest}\n\nTip: You can batch-copy any remaining local outputs from the Plex Sync tab.")
        else:
            messagebox.showinfo("Success", f"Encoding complete!\n\nOutput: {output_file}\n\nTip: You can re-encode with different settings using 'Re-encode Only' button.")


def main():
    # Create Tk root window
    root = tk.Tk()
    
    # Set window to stay on top briefly to ensure it's visible
    root.attributes('-topmost', True)
    root.after(100, lambda: root.attributes('-topmost', False))
    
    # Initialize app
    app = DiscRipperGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
