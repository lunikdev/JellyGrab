"""Tkinter based user interface for JellyGrab."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import os
import threading
from typing import Dict

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from .client import JellyfinClient
from .config import ConfigManager
from .downloads import DownloadController, DownloadItem


class JellyGrabApp:
    """Main UI application."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("JellyGrab 🎬")
        self.root.geometry("950x900")
        self.root.resizable(True, True)

        self.config_manager = ConfigManager()
        self.config = self.config_manager.data

        self.download_path = self.config.get(
            "download_path", str(Path.home() / "Downloads" / "JellyGrab")
        )
        ConfigManager.ensure_download_directory(self.download_path)

        self.max_concurrent_downloads = int(self.config.get("max_concurrent_downloads", 2))
        self.chunk_size_mb = float(self.config.get("chunk_size_mb", 1.0))

        self.client = JellyfinClient(self.config_manager.get_sensitive("server_url", "") or "")

        self.series_data = []
        self.download_ui: Dict[str, Dict[str, object]] = defaultdict(dict)
        self.download_rows: Dict[str, ttk.Frame] = {}
        self.manager_window: tk.Toplevel | None = None
        self.settings_window: tk.Toplevel | None = None
        self.library_map: Dict[str, str] = {}
        self.selected_library_id: str = str(self.config.get("selected_library_id", ""))

        self.download_controller = DownloadController(
            self.client,
            max_concurrent=self.max_concurrent_downloads,
            chunk_size_mb=self.chunk_size_mb,
            on_queue_update=self._queue_update_async,
            on_status=self._status_update_async,
            on_progress=self._progress_update_async,
            on_error=self._error_async,
        )

        self.create_widgets()
        self._attempt_auto_login()

    # ------------------------------------------------------------------
    def _tree_item_exists(self, item_id: str) -> bool:
        return self.series_tree.exists(item_id)

    # ------------------------------------------------------------------
    def create_widgets(self) -> None:
        login_frame = ttk.LabelFrame(self.root, text="🔐 Login no Jellyfin", padding=15)
        login_frame.pack(fill="x", padx=10, pady=10)

        ttk.Label(login_frame, text="URL do Servidor:").grid(row=0, column=0, sticky="w", padx=5, pady=5)
        self.url_entry = ttk.Entry(login_frame, width=50)
        self.url_entry.grid(row=0, column=1, padx=5, pady=5, columnspan=2)
        self.url_entry.insert(0, self.config_manager.get_sensitive("server_url", "") or "")

        ttk.Label(login_frame, text="Usuário:").grid(row=1, column=0, sticky="w", padx=5, pady=5)
        self.username_entry = ttk.Entry(login_frame, width=50)
        self.username_entry.grid(row=1, column=1, padx=5, pady=5, columnspan=2)
        self.username_entry.insert(0, self.config_manager.get_sensitive("username", "") or "")

        ttk.Label(login_frame, text="Senha:").grid(row=2, column=0, sticky="w", padx=5, pady=5)
        self.password_entry = ttk.Entry(login_frame, width=50, show="●")
        self.password_entry.grid(row=2, column=1, padx=5, pady=5, columnspan=2)
        if self.config.get("remember_login"):
            self.password_entry.insert(0, self.config_manager.get_sensitive("password", "") or "")

        self.remember_var = tk.BooleanVar(value=self.config.get("remember_login", False))
        ttk.Checkbutton(login_frame, text="Lembrar login", variable=self.remember_var).grid(
            row=3, column=1, sticky="w", padx=5, pady=5
        )

        self.login_btn = ttk.Button(login_frame, text="🚀 Entrar", command=self.login)
        self.login_btn.grid(row=3, column=2, sticky="e", padx=5, pady=5)

        path_frame = ttk.LabelFrame(self.root, text="📁 Configurações de Download", padding=10)
        path_frame.pack(fill="x", padx=10, pady=5)

        ttk.Label(path_frame, text="Pasta:").pack(side="left", padx=5)
        self.path_entry = ttk.Entry(path_frame, width=60)
        self.path_entry.pack(side="left", padx=5, fill="x", expand=True)
        self.path_entry.insert(0, self.download_path)

        ttk.Button(path_frame, text="📂 Escolher", command=self.choose_folder).pack(side="left", padx=5)
        ttk.Button(path_frame, text="🗂️ Abrir Pasta", command=self.open_download_folder).pack(side="left", padx=5)

        series_frame = ttk.LabelFrame(self.root, text="📺 Séries e Episódios", padding=10)
        series_frame.pack(fill="both", expand=True, padx=10, pady=10)

        search_frame = ttk.Frame(series_frame)
        search_frame.pack(fill="x", pady=(0, 10))

        ttk.Label(search_frame, text="🔍 Buscar:").pack(side="left", padx=5)
        self.search_entry = ttk.Entry(search_frame, width=40)
        self.search_entry.pack(side="left", padx=5, fill="x", expand=True)
        self.search_entry.bind("<KeyRelease>", self.filter_series)

        ttk.Button(search_frame, text="🔄 Atualizar", command=self.load_series).pack(side="left", padx=5)

        ttk.Label(search_frame, text="📚 Mídia:").pack(side="left", padx=5)
        self.library_var = tk.StringVar(value="Selecione uma categoria")
        self.library_combo = ttk.Combobox(
            search_frame,
            textvariable=self.library_var,
            state="disabled",
            width=30,
        )
        self.library_combo.pack(side="left", padx=5)
        self.library_combo.bind("<<ComboboxSelected>>", self.on_library_change)

        tree_frame = ttk.Frame(series_frame)
        tree_frame.pack(fill="both", expand=True)

        columns = ("Nome", "Info", "Status")
        self.series_tree = ttk.Treeview(tree_frame, columns=columns, show="tree headings", height=15)
        self.series_tree.heading("#0", text="📁")
        self.series_tree.heading("Nome", text="Nome")
        self.series_tree.heading("Info", text="Informações")
        self.series_tree.heading("Status", text="Status")
        self.series_tree.column("#0", width=50)
        self.series_tree.column("Nome", width=450)
        self.series_tree.column("Info", width=200)
        self.series_tree.column("Status", width=150)

        scrollbar_y = ttk.Scrollbar(tree_frame, orient="vertical", command=self.series_tree.yview)
        scrollbar_x = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.series_tree.xview)
        self.series_tree.configure(yscrollcommand=scrollbar_y.set, xscrollcommand=scrollbar_x.set)

        self.series_tree.grid(row=0, column=0, sticky="nsew")
        scrollbar_y.grid(row=0, column=1, sticky="ns")
        scrollbar_x.grid(row=1, column=0, sticky="ew")

        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)

        self.series_tree.bind("<Double-Button-1>", self.on_item_double_click)
        self.series_tree.bind("<Button-3>", self.show_context_menu)

        self.context_menu = tk.Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="⬇️ Baixar", command=self.download_selected)
        self.context_menu.add_command(label="📂 Ver Episódios", command=self.load_episodes_from_menu)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="📋 Copiar Nome", command=self.copy_name)

        button_frame = ttk.Frame(self.root)
        button_frame.pack(fill="x", padx=10, pady=10)

        self.download_btn = ttk.Button(button_frame, text="⬇️ Baixar Selecionado", command=self.download_selected, state="disabled")
        self.download_btn.pack(side="left", padx=5)

        self.download_season_btn = ttk.Button(
            button_frame,
            text="📥 Baixar Temporada Completa",
            command=self.download_season,
            state="disabled",
        )
        self.download_season_btn.pack(side="left", padx=5)

        self.manager_btn = ttk.Button(
            button_frame,
            text="📥 Gerenciar Downloads",
            command=self.open_download_manager,
            state="disabled",
        )
        self.manager_btn.pack(side="left", padx=5)

        self.settings_btn = ttk.Button(
            button_frame,
            text="⚙️ Configurações",
            command=self.open_settings,
        )
        self.settings_btn.pack(side="left", padx=5)

        status_frame = ttk.Frame(self.root)
        status_frame.pack(fill="x", padx=10, pady=5)

        self.status_label = ttk.Label(
            status_frame,
            text="🔴 Desconectado - Faça login para começar",
            relief="sunken",
            anchor="w",
        )
        self.status_label.pack(side="left", fill="x", expand=True)

        self.queue_label = ttk.Label(status_frame, text="Fila: 0 | Ativos: 0", anchor="e")
        self.queue_label.pack(side="right", padx=5)

        self.progress = ttk.Progressbar(self.root, mode="determinate")
        self.progress.pack(fill="x", padx=10, pady=5)

    # ------------------------------------------------------------------
    def _attempt_auto_login(self) -> None:
        if self.config.get("remember_login") and self.config_manager.get_sensitive("username"):
            self.root.after(500, self.login)

    # ------------------------------------------------------------------
    def choose_folder(self) -> None:
        folder = filedialog.askdirectory(initialdir=self.download_path)
        if folder:
            self.download_path = folder
            self.path_entry.delete(0, tk.END)
            self.path_entry.insert(0, folder)
            self.config_manager.set("download_path", folder)
            ConfigManager.ensure_download_directory(folder)

    # ------------------------------------------------------------------
    def open_download_folder(self) -> None:
        try:
            if os.path.exists(self.download_path):
                if os.name == "nt":
                    os.startfile(self.download_path)  # type: ignore[attr-defined]
                elif os.name == "posix":
                    os.system(f'xdg-open "{self.download_path}" >/dev/null 2>&1 &')
                else:
                    messagebox.showinfo("Info", self.download_path)
            else:
                messagebox.showwarning("Aviso", "Pasta não existe!")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Erro", f"Não foi possível abrir a pasta: {exc}")

    # ------------------------------------------------------------------
    def show_context_menu(self, event: tk.Event) -> None:  # type: ignore[override]
        item = self.series_tree.identify_row(event.y)
        if item:
            self.series_tree.selection_set(item)
            self.context_menu.post(event.x_root, event.y_root)

    # ------------------------------------------------------------------
    def copy_name(self) -> None:
        selection = self.series_tree.selection()
        if selection:
            item = selection[0]
            name = self.series_tree.item(item)["values"][0]
            self.root.clipboard_clear()
            self.root.clipboard_append(name)
            self.status_label.config(text=f"📋 Nome copiado: {name}")

    # ------------------------------------------------------------------
    def login(self) -> None:
        server_url = self.url_entry.get().strip().rstrip("/")
        username = self.username_entry.get().strip()
        password = self.password_entry.get().strip()

        if not all([server_url, username, password]):
            messagebox.showerror("Erro", "Preencha todos os campos!")
            return

        self.status_label.config(text="🔄 Conectando ao servidor...")
        self.login_btn.config(state="disabled")

        def do_login() -> None:
            try:
                self.client.configure(server_url)
                self.client.authenticate(username, password)
            except PermissionError as exc:
                self._async(lambda: messagebox.showerror("Erro de Login", str(exc)))
                self._async(lambda: self.status_label.config(text="❌ Falha no login"))
                self._async(lambda: self.login_btn.config(state="normal"))
                return
            except Exception as exc:  # noqa: BLE001
                self._async(lambda: messagebox.showerror("Erro", f"Erro ao conectar: {exc}"))
                self._async(lambda: self.status_label.config(text="❌ Erro na conexão"))
                self._async(lambda: self.login_btn.config(state="normal"))
                return

            def on_success() -> None:
                self.status_label.config(text=f"✅ Conectado como {username}")
                self.login_btn.config(state="normal")
                self.download_btn.config(state="normal")
                self.download_season_btn.config(state="normal")
                self.manager_btn.config(state="normal")
                remember_login = self.remember_var.get()
                self.config_manager.update({"remember_login": remember_login})
                self.config_manager.set_sensitive("server_url", server_url)
                self.config_manager.set_sensitive("username", username)
                if remember_login and password:
                    self.config_manager.set_sensitive("password", password)
                else:
                    self.config_manager.clear_sensitive("password")
                messagebox.showinfo("Sucesso", f"Login realizado com sucesso!\nBem-vindo, {username}! 🎉")
                self.load_libraries()

            self._async(on_success)

        threading.Thread(target=do_login, daemon=True).start()

    # ------------------------------------------------------------------
    def _async(self, callback) -> None:
        self.root.after(0, callback)

    # ------------------------------------------------------------------
    def open_settings(self) -> None:
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.focus_set()
            return

        self.settings_window = tk.Toplevel(self.root)
        self.settings_window.title("Configurações")
        self.settings_window.geometry("400x220")
        self.settings_window.resizable(False, False)
        self.settings_window.grab_set()
        self.settings_window.protocol("WM_DELETE_WINDOW", self.close_settings)

        container = ttk.Frame(self.settings_window, padding=15)
        container.pack(fill="both", expand=True)

        ttk.Label(container, text="Downloads simultâneos:").grid(row=0, column=0, sticky="w", pady=(0, 10))
        self.concurrent_var = tk.IntVar(value=self.max_concurrent_downloads)
        concurrent_spin = ttk.Spinbox(
            container,
            from_=1,
            to=10,
            textvariable=self.concurrent_var,
            width=5,
        )
        concurrent_spin.grid(row=0, column=1, sticky="e", pady=(0, 10))

        ttk.Label(container, text="Tamanho do bloco (MB):").grid(row=1, column=0, sticky="w", pady=(0, 10))
        self.chunk_size_var = tk.DoubleVar(value=self.chunk_size_mb)
        chunk_spin = ttk.Spinbox(
            container,
            from_=0.25,
            to=10,
            increment=0.25,
            textvariable=self.chunk_size_var,
            width=5,
            format="%.2f",
        )
        chunk_spin.grid(row=1, column=1, sticky="e", pady=(0, 10))

        helper = ttk.Label(
            container,
            text="Ajuste o tamanho do bloco para melhorar a velocidade. Valores maiores utilizam mais memória.",
            wraplength=320,
            foreground="#555555",
            justify="left",
        )
        helper.grid(row=2, column=0, columnspan=2, sticky="w", pady=(0, 15))

        button_frame = ttk.Frame(container)
        button_frame.grid(row=3, column=0, columnspan=2, sticky="e")

        ttk.Button(button_frame, text="Cancelar", command=self.close_settings).pack(side="right", padx=5)
        ttk.Button(button_frame, text="Salvar", command=self.save_settings).pack(side="right")

    # ------------------------------------------------------------------
    def close_settings(self) -> None:
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.grab_release()
            self.settings_window.destroy()
        self.settings_window = None

    # ------------------------------------------------------------------
    def save_settings(self) -> None:
        try:
            concurrent = int(self.concurrent_var.get())
        except (tk.TclError, ValueError):
            messagebox.showerror("Erro", "Valor inválido para downloads simultâneos")
            return

        try:
            chunk_size = float(self.chunk_size_var.get())
        except (tk.TclError, ValueError):
            messagebox.showerror("Erro", "Valor inválido para o tamanho do bloco")
            return

        concurrent = max(1, concurrent)
        chunk_size = max(0.25, chunk_size)

        self.max_concurrent_downloads = concurrent
        self.chunk_size_mb = chunk_size

        self.download_controller.set_max_concurrent(concurrent)
        self.download_controller.set_chunk_size_mb(chunk_size)

        self.config_manager.update(
            {
                "max_concurrent_downloads": self.max_concurrent_downloads,
                "chunk_size_mb": self.chunk_size_mb,
            }
        )

        self.status_label.config(text="⚙️ Configurações atualizadas")
        self.close_settings()

    # ------------------------------------------------------------------
    def clear_series_tree(self) -> None:
        for item in self.series_tree.get_children():
            self.series_tree.delete(item)
        self.series_data = []

    # ------------------------------------------------------------------
    def load_libraries(self) -> None:
        if not self.client.access_token:
            return

        self.status_label.config(text="📡 Carregando bibliotecas...")
        self.library_combo.config(state="disabled")

        def fetch_libraries() -> None:
            try:
                data = self.client.list_views()
            except Exception as exc:  # noqa: BLE001
                self._async(lambda: messagebox.showerror("Erro", f"Erro ao carregar bibliotecas: {exc}"))
                self._async(lambda: self.status_label.config(text="❌ Erro ao carregar bibliotecas"))
                self._async(lambda: self.library_combo.config(state="readonly" if self.library_map else "disabled"))
            else:
                items = data.get("Items", [])
                mapping = {view.get("Name", "Sem nome"): view.get("Id", "") for view in items if view.get("Id")}
                self._async(lambda: self._populate_libraries(mapping))

        threading.Thread(target=fetch_libraries, daemon=True).start()

    # ------------------------------------------------------------------
    def _populate_libraries(self, mapping: Dict[str, str]) -> None:
        self.library_map = mapping
        values = list(mapping.keys())

        if not values:
            self.library_combo.set("Nenhuma biblioteca disponível")
            self.library_combo.config(state="disabled")
            self.clear_series_tree()
            return

        self.library_combo.config(state="readonly")
        self.library_combo["values"] = values

        preferred_id = self.selected_library_id or str(self.config.get("selected_library_id", ""))
        selected_name = next((name for name, ident in mapping.items() if ident == preferred_id), values[0])
        self.library_combo.set(selected_name)
        self.selected_library_id = mapping.get(selected_name, "")

        if self.selected_library_id:
            self.config_manager.set("selected_library_id", self.selected_library_id)
            self.load_series()

    # ------------------------------------------------------------------
    def on_library_change(self, event=None) -> None:  # noqa: ANN001
        selected_name = self.library_var.get()
        selected_id = self.library_map.get(selected_name, "")

        if selected_id == self.selected_library_id:
            return

        self.selected_library_id = selected_id

        if not selected_id:
            self.clear_series_tree()
            self.status_label.config(text="🔔 Selecione uma biblioteca válida")
            return

        self.config_manager.set("selected_library_id", selected_id)
        self.load_series()

    # ------------------------------------------------------------------
    def load_series(self) -> None:
        if not self.client.access_token:
            messagebox.showwarning("Aviso", "Faça login primeiro!")
            return

        if not self.selected_library_id:
            self.status_label.config(text="🔔 Selecione uma biblioteca para carregar")
            self.clear_series_tree()
            return

        self.status_label.config(text="📡 Carregando séries...")
        self.progress.config(mode="indeterminate")
        self.progress.start()

        def fetch_series() -> None:
            try:
                data = self.client.list_series(self.selected_library_id)
            except Exception as exc:  # noqa: BLE001
                self._async(lambda: messagebox.showerror("Erro", f"Erro: {exc}"))
                self._async(lambda: self.status_label.config(text="❌ Erro ao carregar"))
                self._async(self.clear_series_tree)
            else:
                self.series_data = data.get("Items", [])
                self._async(self.update_series_tree)
                self._async(lambda: self.status_label.config(text=f"✅ {len(self.series_data)} séries carregadas"))
            finally:
                self._async(self.progress.stop)
                self._async(lambda: self.progress.config(mode="determinate"))

        threading.Thread(target=fetch_series, daemon=True).start()

    # ------------------------------------------------------------------
    def filter_series(self, event=None) -> None:  # noqa: ANN001
        search_term = self.search_entry.get().lower()
        for item in self.series_tree.get_children():
            self.series_tree.delete(item)

        filtered = [series for series in self.series_data if search_term in series.get("Name", "").lower()]

        for series in filtered:
            name = series.get("Name", "Sem nome")
            year = series.get("ProductionYear", "")
            series_id = series.get("Id")
            info = f"Ano: {year}" if year else "Ano desconhecido"
            self.series_tree.insert("", "end", iid=series_id, text="📺", values=(name, info, "Clique 2x para ver episódios"))

    # ------------------------------------------------------------------
    def update_series_tree(self) -> None:
        self.filter_series()

    # ------------------------------------------------------------------
    def on_item_double_click(self, event) -> None:  # noqa: ANN001
        selection = self.series_tree.selection()
        if not selection:
            return

        item_id = selection[0]
        parent = self.series_tree.parent(item_id)
        grandparent = self.series_tree.parent(parent)

        if not parent:
            self.load_episodes(item_id)
        elif not grandparent:
            self.download_season(item_id)
        else:
            self.queue_download_episode(item_id)

    # ------------------------------------------------------------------
    def load_episodes_from_menu(self) -> None:
        selection = self.series_tree.selection()
        if selection:
            item_id = selection[0]
            parent = self.series_tree.parent(item_id)
            if not parent:
                self.load_episodes(item_id)

    # ------------------------------------------------------------------
    def load_episodes(self, series_id: str) -> None:
        self.status_label.config(text="📡 Carregando episódios...")
        self.progress.config(mode="indeterminate")
        self.progress.start()

        def fetch_episodes() -> None:
            try:
                data = self.client.list_episodes(series_id)
            except Exception as exc:  # noqa: BLE001
                self._async(lambda: messagebox.showerror("Erro", f"Erro: {exc}"))
                self._async(self.progress.stop)
                return

            episodes = data.get("Items", [])
            for child in self.series_tree.get_children(series_id):
                self.series_tree.delete(child)

            seasons: Dict[int, list] = defaultdict(list)
            for episode in episodes:
                season_num = episode.get("ParentIndexNumber", 0)
                seasons[season_num].append(episode)

            series_name = self.series_tree.item(series_id)["values"][0]

            for season_num in sorted(seasons):
                season_id = f"{series_id}_season_{season_num}"
                season_episodes = seasons[season_num]
                self._async(
                    lambda sid=series_id, ssid=season_id, sn=season_num, count=len(season_episodes): self.series_tree.insert(
                        sid,
                        "end",
                        iid=ssid,
                        text="📁",
                        values=(f"Temporada {sn}", f"{count} episódios", "Clique 2x para baixar todos"),
                    )
                )

                for ep in season_episodes:
                    ep_name = ep.get("Name", "Sem nome")
                    season_index = ep.get("ParentIndexNumber", 0)
                    episode_index = ep.get("IndexNumber", 0)
                    ep_id = ep.get("Id")
                    display_name = f"E{episode_index:02d} - {ep_name}"

                    safe_series = "".join(c for c in series_name if c.isalnum() or c in (" ", "-", "_"))
                    safe_ep = "".join(c for c in ep_name if c.isalnum() or c in (" ", "-", "_"))
                    filename = f"{safe_series} - S{season_index:02d}E{episode_index:02d} - {safe_ep}.mp4"
                    filepath = Path(self.download_path) / safe_series / filename
                    status = "✅ Já baixado" if filepath.exists() else "⬇️ Pronto para baixar"

                    self._async(
                        lambda ssid=season_id, eid=ep_id, dn=display_name, st=status: self.series_tree.insert(
                            ssid,
                            "end",
                            iid=eid,
                            text="🎬",
                            values=(dn, "", st),
                        )
                    )

            self._async(lambda: self.series_tree.item(series_id, open=True))
            self._async(lambda: self.status_label.config(text=f"✅ {len(episodes)} episódios carregados"))
            self._async(self.progress.stop)
            self._async(lambda: self.progress.config(mode="determinate"))

        threading.Thread(target=fetch_episodes, daemon=True).start()

    # ------------------------------------------------------------------
    def download_selected(self) -> None:
        selection = self.series_tree.selection()
        if not selection:
            messagebox.showwarning("Aviso", "Selecione um episódio!")
            return

        item_id = selection[0]
        parent = self.series_tree.parent(item_id)
        grandparent = self.series_tree.parent(parent)

        if not parent:
            messagebox.showinfo("Info", "Selecione um episódio específico, não a série.")
            return

        if not grandparent:
            self.download_season(item_id)
        else:
            self.queue_download_episode(item_id)

    # ------------------------------------------------------------------
    def download_season(self, season_id: str | None = None) -> None:
        if not season_id:
            selection = self.series_tree.selection()
            if not selection:
                messagebox.showwarning("Aviso", "Selecione uma temporada!")
                return
            season_id = selection[0]

        episodes = self.series_tree.get_children(season_id)
        if not episodes:
            messagebox.showinfo("Info", "Nenhum episódio encontrado nesta temporada")
            return

        to_download = [ep for ep in episodes if "✅" not in self.series_tree.item(ep)["values"][2]]
        if not to_download:
            messagebox.showinfo("Info", "Todos os episódios desta temporada já foram baixados!")
            return

        if not messagebox.askyesno("Confirmar", f"Deseja baixar {len(to_download)} episódios?"):
            return

        for episode_id in to_download:
            self.queue_download_episode(episode_id, show_success=False)

    # ------------------------------------------------------------------
    def queue_download_episode(self, episode_id: str, show_success: bool = True) -> None:
        current_values = self.series_tree.item(episode_id)["values"]
        if "✅" in current_values[2]:
            if show_success:
                messagebox.showinfo("Info", "Este episódio já foi baixado!")
            return

        self.series_tree.item(episode_id, values=(current_values[0], "", "🔄 Preparando..."))

        def worker() -> None:
            try:
                self.download_controller.queue_episode(
                    episode_id,
                    Path(self.download_path),
                    show_success=show_success,
                )
            except Exception as exc:  # noqa: BLE001
                self._async(
                    lambda: self.series_tree.item(
                        episode_id,
                        values=(current_values[0], "", "❌ Erro"),
                    )
                )
                self._async(lambda: messagebox.showerror("Erro", f"Erro ao preparar: {exc}"))

        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------------
    def _ensure_download_state(self, item: DownloadItem) -> Dict[str, tk.Variable]:
        if item.episode_id not in self.download_ui:
            self.download_ui[item.episode_id] = {
                "progress": tk.DoubleVar(value=0),
                "status": tk.StringVar(value=item.status),
                "speed": tk.StringVar(value="0 MB/s"),
                "eta": tk.StringVar(value=""),
                "downloaded": 0,
                "total": 0,
                "filename": item.filename,
            }
        return self.download_ui[item.episode_id]

    # ------------------------------------------------------------------
    def _remove_download_entry(self, episode_id: str) -> None:
        frame = self.download_rows.pop(episode_id, None)
        if frame and frame.winfo_exists():
            frame.destroy()
        self.download_ui.pop(episode_id, None)

    # ------------------------------------------------------------------
    def _queue_update_async(self) -> None:
        self._async(self.update_queue_status)

    def update_queue_status(self) -> None:
        queue_size = self.download_controller.queue_size()
        active = self.download_controller.current_downloads
        self.queue_label.config(text=f"Fila: {queue_size} | Ativos: {active}")

    # ------------------------------------------------------------------
    def _status_update_async(self, item: DownloadItem, status: str) -> None:
        self._async(lambda: self._handle_status(item, status))

    def _handle_status(self, item: DownloadItem, status: str) -> None:
        state = self._ensure_download_state(item)
        state["status"].set(status)

        if self._tree_item_exists(item.episode_id):
            current_values = list(self.series_tree.item(item.episode_id)["values"])
            name = current_values[0] if current_values else item.filename
            info = current_values[1] if len(current_values) > 1 else ""
            self.series_tree.item(item.episode_id, values=(name, info, status))

        if status in {"✅ Concluído", "❌ Erro", "🚫 Cancelado"}:
            state["progress"].set(100 if status == "✅ Concluído" else state["progress"].get())
            state["speed"].set("0.00 MB/s")
            state["eta"].set("0s")
            if status == "✅ Concluído":
                state["downloaded"] = item.total_size
                state["total"] = item.total_size
            if status == "🚫 Cancelado":
                self._remove_download_entry(item.episode_id)

    # ------------------------------------------------------------------
    def _progress_update_async(self, item: DownloadItem, payload) -> None:  # noqa: ANN001
        self._async(lambda: self._handle_progress(item, payload))

    def _handle_progress(self, item: DownloadItem, payload) -> None:
        state = self._ensure_download_state(item)
        percent = payload.get("percent", 0.0)
        downloaded = payload.get("downloaded", 0)
        total_size = payload.get("total_size", 0)
        speed = payload.get("speed", "0 MB/s")
        eta = payload.get("eta", "")

        state["progress"].set(percent)
        state["speed"].set(speed)
        state["eta"].set(eta)
        state["downloaded"] = downloaded
        state["total"] = total_size

        mb_downloaded = downloaded / (1024 * 1024)
        mb_total = total_size / (1024 * 1024) if total_size else 0
        info_text = (
            f"{percent:.1f}% | {speed} | {mb_downloaded:.1f}/{mb_total:.1f} MB | ETA: {eta}"
            if total_size
            else f"{mb_downloaded:.1f} MB baixados | {speed}"
        )

        if self._tree_item_exists(item.episode_id):
            current_values = list(self.series_tree.item(item.episode_id)["values"])
            name = current_values[0] if current_values else item.filename
            self.series_tree.item(item.episode_id, values=(name, info_text, item.status))

    # ------------------------------------------------------------------
    def _error_async(self, item: DownloadItem, exc: Exception) -> None:  # noqa: BLE001
        self._async(lambda: messagebox.showerror("Erro", f"Erro no download: {exc}"))

    # ------------------------------------------------------------------
    def cancel_download(self, episode_id: str) -> None:
        self.download_controller.cancel(episode_id)
        if episode_id in self.download_ui:
            self.download_ui[episode_id]["status"].set("🚫 Cancelando...")
        if self._tree_item_exists(episode_id):
            values = list(self.series_tree.item(episode_id)["values"])
            values[2] = "🚫 Cancelando..."
            self.series_tree.item(episode_id, values=tuple(values))

    # ------------------------------------------------------------------
    def open_download_manager(self) -> None:
        if self.manager_window and self.manager_window.winfo_exists():
            self.manager_window.lift()
            return

        self.manager_window = tk.Toplevel(self.root)
        self.manager_window.title("Gerenciador de Downloads")
        self.manager_window.geometry("800x600")
        self.manager_window.protocol("WM_DELETE_WINDOW", self.close_manager)

        canvas = tk.Canvas(self.manager_window)
        scrollbar = ttk.Scrollbar(self.manager_window, orient="vertical", command=canvas.yview)
        self.scrollable_frame = ttk.Frame(canvas)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )

        canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        total_frame = ttk.Frame(self.scrollable_frame)
        total_frame.pack(fill="x", pady=10, padx=10)

        ttk.Label(total_frame, text="Progresso Total:").pack(side="left", padx=5)
        self.total_progress_var = tk.DoubleVar(value=0)
        total_prog = ttk.Progressbar(total_frame, variable=self.total_progress_var, maximum=100, length=300)
        total_prog.pack(side="left", fill="x", expand=True, padx=5)

        self.total_percent_var = tk.StringVar(value="0%")
        ttk.Label(total_frame, textvariable=self.total_percent_var).pack(side="left", padx=5)

        self.total_speed_var = tk.StringVar(value="0 MB/s")
        ttk.Label(total_frame, text="Velocidade:", anchor="e").pack(side="left", padx=5)
        ttk.Label(total_frame, textvariable=self.total_speed_var).pack(side="left", padx=5)

        self.download_rows = {}
        self.update_manager()

    # ------------------------------------------------------------------
    def update_manager(self) -> None:
        if not self.manager_window or not self.manager_window.winfo_exists():
            return

        for episode_id, item in list(self.download_controller.items.items()):
            state = self._ensure_download_state(item)
            if episode_id not in self.download_rows:
                row_frame = ttk.LabelFrame(self.scrollable_frame, text=item.filename, padding=5)
                row_frame.pack(fill="x", pady=5, padx=10)

                prog_frame = ttk.Frame(row_frame)
                prog_frame.pack(fill="x")

                prog = ttk.Progressbar(prog_frame, variable=state["progress"], maximum=100, length=200)
                prog.pack(side="left", fill="x", expand=True, padx=5)

                percent_label = ttk.Label(prog_frame, text="0%")

                def update_percent(var_name, index, mode, item_state=state, label=percent_label):  # noqa: ANN001
                    percent = item_state["progress"].get()
                    total = item_state.get("total", 0)
                    label.config(text=f"{percent:.1f}%" if total else "...")

                state["progress"].trace_add("write", update_percent)
                percent_label.pack(side="left", padx=5)

                details_frame = ttk.Frame(row_frame)
                details_frame.pack(fill="x", pady=5)

                ttk.Label(details_frame, text="Velocidade:").pack(side="left", padx=(0, 5))
                ttk.Label(details_frame, textvariable=state["speed"]).pack(side="left", padx=(0, 10))

                ttk.Label(details_frame, text="ETA:").pack(side="left", padx=(0, 5))
                ttk.Label(details_frame, textvariable=state["eta"]).pack(side="left", padx=(0, 10))

                ttk.Label(details_frame, text="Status:").pack(side="left", padx=(0, 5))
                ttk.Label(details_frame, textvariable=state["status"]).pack(side="left", padx=(0, 10))

                cancel_btn = ttk.Button(details_frame, text="Cancelar", command=lambda eid=episode_id: self.cancel_download(eid))
                cancel_btn.pack(side="right", padx=5)
                state["cancel_btn"] = cancel_btn

                self.download_rows[episode_id] = row_frame

        total_downloaded = 0
        total_size = 0
        total_speed = 0.0
        for episode_id, item in self.download_controller.items.items():
            state = self._ensure_download_state(item)
            status = state["status"].get()
            if status in ("Concluído", "❌ Erro", "🚫 Cancelado"):
                cancel_btn = state.get("cancel_btn")
                if cancel_btn and cancel_btn.winfo_exists():
                    cancel_btn.config(state="disabled")

            if status not in ("❌ Erro", "🚫 Cancelado"):
                total_downloaded += state.get("downloaded", 0)
                total_size += state.get("total", 0)
                try:
                    total_speed += float(state["speed"].get().split()[0])
                except Exception:  # noqa: BLE001
                    pass

        if total_size > 0:
            percent = (total_downloaded / total_size) * 100
            self.total_progress_var.set(percent)
            self.total_percent_var.set(f"{percent:.1f}%")
        else:
            self.total_progress_var.set(0)
            self.total_percent_var.set("0%")

        self.total_speed_var.set(f"{total_speed:.2f} MB/s")

        for episode_id in list(self.download_rows.keys()):
            if episode_id not in self.download_controller.items:
                frame = self.download_rows.pop(episode_id)
                if frame.winfo_exists():
                    frame.destroy()

        for episode_id in list(self.download_ui.keys()):
            if episode_id not in self.download_controller.items:
                self.download_ui.pop(episode_id, None)

        self.manager_window.after(1000, self.update_manager)

    # ------------------------------------------------------------------
    def close_manager(self) -> None:
        if self.manager_window:
            self.manager_window.destroy()
        self.manager_window = None


__all__ = ["JellyGrabApp"]
