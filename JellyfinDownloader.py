import requests
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import os
import threading
from pathlib import Path
import json
import hashlib
import queue
import time

class JellyfinDownloader:
    def __init__(self, root):
        self.root = root
        self.root.title("Jellyfin Downloader 🎬")
        self.root.geometry("950x750")
        self.root.resizable(True, True)
        
        # Configurações
        self.config_file = "jellyfin_config.json"
        self.load_config()
        
        # Variáveis de sessão
        self.user_id = None
        self.access_token = None
        self.server_url = None
        self.device_id = None
        self.series_data = []
        self.download_path = self.config.get("download_path", str(Path.home() / "Downloads" / "Jellyfin"))
        
        # Cria pasta de download se não existir
        os.makedirs(self.download_path, exist_ok=True)
        
        # Fila de downloads
        self.download_queue = queue.Queue()
        self.max_concurrent = 2
        self.current_downloads = 0
        self.download_items = {}
        self.manager_window = None
        
        self.create_widgets()
        
        # Inicia workers de download
        for _ in range(self.max_concurrent):
            threading.Thread(target=self.download_worker, daemon=True).start()
        
        # Tenta login automático se tiver credenciais salvas
        if self.config.get("remember_login") and self.config.get("username"):
            self.root.after(500, self.auto_login)
    
    def load_config(self):
        """Carrega configurações salvas"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    self.config = json.load(f)
            else:
                self.config = {}
        except:
            self.config = {}
    
    def save_config(self):
        """Salva configurações"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Erro ao salvar config: {e}")
    
    def generate_device_id(self):
        """Gera um Device ID único baseado no computador"""
        import platform
        info = f"{platform.node()}-{platform.system()}-{platform.machine()}"
        return hashlib.md5(info.encode()).hexdigest()
    
    def create_widgets(self):
        """Cria interface gráfica"""
        
        # Frame de Login
        login_frame = ttk.LabelFrame(self.root, text="🔐 Login no Jellyfin", padding=15)
        login_frame.pack(fill="x", padx=10, pady=10)
        
        # URL do servidor
        ttk.Label(login_frame, text="URL do Servidor:").grid(row=0, column=0, sticky="w", padx=5, pady=5)
        self.url_entry = ttk.Entry(login_frame, width=50)
        self.url_entry.grid(row=0, column=1, padx=5, pady=5, columnspan=2)
        self.url_entry.insert(0, self.config.get("server_url", ""))
        
        # Username
        ttk.Label(login_frame, text="Usuário:").grid(row=1, column=0, sticky="w", padx=5, pady=5)
        self.username_entry = ttk.Entry(login_frame, width=50)
        self.username_entry.grid(row=1, column=1, padx=5, pady=5, columnspan=2)
        self.username_entry.insert(0, self.config.get("username", ""))
        
        # Password
        ttk.Label(login_frame, text="Senha:").grid(row=2, column=0, sticky="w", padx=5, pady=5)
        self.password_entry = ttk.Entry(login_frame, width=50, show="●")
        self.password_entry.grid(row=2, column=1, padx=5, pady=5, columnspan=2)
        if self.config.get("remember_login"):
            self.password_entry.insert(0, self.config.get("password", ""))
        
        # Checkbox lembrar login
        self.remember_var = tk.BooleanVar(value=self.config.get("remember_login", False))
        ttk.Checkbutton(login_frame, text="Lembrar login", variable=self.remember_var).grid(row=3, column=1, sticky="w", padx=5, pady=5)
        
        # Botão de login
        self.login_btn = ttk.Button(login_frame, text="🚀 Entrar", command=self.login)
        self.login_btn.grid(row=3, column=2, sticky="e", padx=5, pady=5)
        
        # Frame de Pasta de Download
        path_frame = ttk.LabelFrame(self.root, text="📁 Configurações de Download", padding=10)
        path_frame.pack(fill="x", padx=10, pady=5)
        
        ttk.Label(path_frame, text="Pasta:").pack(side="left", padx=5)
        self.path_entry = ttk.Entry(path_frame, width=60)
        self.path_entry.pack(side="left", padx=5, fill="x", expand=True)
        self.path_entry.insert(0, self.download_path)
        
        ttk.Button(path_frame, text="📂 Escolher", command=self.choose_folder).pack(side="left", padx=5)
        ttk.Button(path_frame, text="🗂️ Abrir Pasta", command=self.open_download_folder).pack(side="left", padx=5)
        
        # Frame de Séries
        series_frame = ttk.LabelFrame(self.root, text="📺 Séries e Episódios", padding=10)
        series_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Barra de busca
        search_frame = ttk.Frame(series_frame)
        search_frame.pack(fill="x", pady=(0, 10))
        
        ttk.Label(search_frame, text="🔍 Buscar:").pack(side="left", padx=5)
        self.search_entry = ttk.Entry(search_frame, width=40)
        self.search_entry.pack(side="left", padx=5, fill="x", expand=True)
        self.search_entry.bind("<KeyRelease>", self.filter_series)
        
        ttk.Button(search_frame, text="🔄 Atualizar", command=self.load_series).pack(side="left", padx=5)
        
        # Treeview para séries
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
        
        # Menu de contexto
        self.context_menu = tk.Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="⬇️ Baixar", command=self.download_selected)
        self.context_menu.add_command(label="📂 Ver Episódios", command=self.load_episodes_from_menu)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="📋 Copiar Nome", command=self.copy_name)
        
        # Botões de ação
        button_frame = ttk.Frame(self.root)
        button_frame.pack(fill="x", padx=10, pady=10)
        
        self.download_btn = ttk.Button(button_frame, text="⬇️ Baixar Selecionado", command=self.download_selected, state="disabled")
        self.download_btn.pack(side="left", padx=5)
        
        self.download_season_btn = ttk.Button(button_frame, text="📥 Baixar Temporada Completa", command=self.download_season, state="disabled")
        self.download_season_btn.pack(side="left", padx=5)
        
        self.manager_btn = ttk.Button(button_frame, text="📥 Gerenciar Downloads", command=self.open_download_manager, state="disabled")
        self.manager_btn.pack(side="left", padx=5)
        
        # Status
        status_frame = ttk.Frame(self.root)
        status_frame.pack(fill="x", padx=10, pady=5)
        
        self.status_label = ttk.Label(status_frame, text="🔴 Desconectado - Faça login para começar", relief="sunken", anchor="w")
        self.status_label.pack(side="left", fill="x", expand=True)
        
        self.queue_label = ttk.Label(status_frame, text="Fila: 0 | Ativos: 0", anchor="e")
        self.queue_label.pack(side="right", padx=5)
        
        # Progress bar
        self.progress = ttk.Progressbar(self.root, mode="determinate")
        self.progress.pack(fill="x", padx=10, pady=5)
    
    def download_worker(self):
        while True:
            episode_id, show_success = self.download_queue.get()
            self.current_downloads += 1
            self.update_queue_status()
            try:
                self.download_episode_core(episode_id, show_success)
            finally:
                self.current_downloads -= 1
                self.update_queue_status()
                self.download_queue.task_done()
    
    def update_queue_status(self):
        qsize = self.download_queue.qsize()
        self.root.after(0, lambda: self.queue_label.config(text=f"Fila: {qsize} | Ativos: {self.current_downloads}"))
    
    def show_context_menu(self, event):
        """Mostra menu de contexto"""
        item = self.series_tree.identify_row(event.y)
        if item:
            self.series_tree.selection_set(item)
            self.context_menu.post(event.x_root, event.y_root)
    
    def copy_name(self):
        """Copia nome do item selecionado"""
        selection = self.series_tree.selection()
        if selection:
            item = selection[0]
            name = self.series_tree.item(item)["values"][0]
            self.root.clipboard_clear()
            self.root.clipboard_append(name)
            self.status_label.config(text=f"📋 Nome copiado: {name}")
    
    def choose_folder(self):
        """Escolhe pasta de download"""
        folder = filedialog.askdirectory(initialdir=self.download_path)
        if folder:
            self.download_path = folder
            self.path_entry.delete(0, tk.END)
            self.path_entry.insert(0, folder)
            self.config["download_path"] = folder
            self.save_config()
            os.makedirs(folder, exist_ok=True)
    
    def open_download_folder(self):
        """Abre pasta de downloads"""
        try:
            if os.path.exists(self.download_path):
                os.startfile(self.download_path)
            else:
                messagebox.showwarning("Aviso", "Pasta não existe!")
        except:
            messagebox.showerror("Erro", "Não foi possível abrir a pasta")
    
    def auto_login(self):
        """Tenta fazer login automático"""
        if self.config.get("remember_login"):
            self.login()
    
    def login(self):
        """Faz login no Jellyfin"""
        self.server_url = self.url_entry.get().strip().rstrip('/')
        username = self.username_entry.get().strip()
        password = self.password_entry.get().strip()
        
        if not all([self.server_url, username, password]):
            messagebox.showerror("Erro", "Preencha todos os campos!")
            return
        
        self.status_label.config(text="🔄 Conectando ao servidor...")
        self.login_btn.config(state="disabled")
        
        def do_login():
            try:
                # Gera Device ID único
                self.device_id = self.generate_device_id()
                
                # Endpoint de autenticação
                auth_url = f"{self.server_url}/Users/authenticatebyname"
                
                headers = {
                    "Content-Type": "application/json",
                    "X-Emby-Authorization": f'MediaBrowser Client="Jellyfin Downloader", Device="Python", DeviceId="{self.device_id}", Version="1.0.0"'
                }
                
                payload = {
                    "Username": username,
                    "Pw": password
                }
                
                response = requests.post(auth_url, json=payload, headers=headers, timeout=15)
                
                if response.status_code == 200:
                    data = response.json()
                    
                    # Extrai informações da sessão
                    self.access_token = data.get("AccessToken")
                    self.user_id = data.get("User", {}).get("Id")
                    
                    if not self.access_token or not self.user_id:
                        raise Exception("Falha ao obter token de acesso")
                    
                    # Salva configurações
                    self.config.update({
                        "server_url": self.server_url,
                        "username": username,
                        "remember_login": self.remember_var.get()
                    })
                    
                    if self.remember_var.get():
                        self.config["password"] = password
                    else:
                        self.config.pop("password", None)
                    
                    self.save_config()
                    
                    # Atualiza UI
                    self.root.after(0, lambda: self.status_label.config(text=f"✅ Conectado como {username}"))
                    self.root.after(0, lambda: self.login_btn.config(state="normal"))
                    self.root.after(0, lambda: self.download_btn.config(state="normal"))
                    self.root.after(0, lambda: self.download_season_btn.config(state="normal"))
                    self.root.after(0, lambda: self.manager_btn.config(state="normal"))
                    self.root.after(0, self.load_series)
                    
                    self.root.after(0, lambda: messagebox.showinfo("Sucesso", f"Login realizado com sucesso!\nBem-vindo, {username}! 🎉"))
                    
                else:
                    error_msg = response.json().get("Message", "Credenciais inválidas")
                    self.root.after(0, lambda: messagebox.showerror("Erro de Login", error_msg))
                    self.root.after(0, lambda: self.status_label.config(text="❌ Falha no login"))
                    self.root.after(0, lambda: self.login_btn.config(state="normal"))
                    
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("Erro", f"Erro ao conectar: {str(e)}"))
                self.root.after(0, lambda: self.status_label.config(text="❌ Erro na conexão"))
                self.root.after(0, lambda: self.login_btn.config(state="normal"))
        
        threading.Thread(target=do_login, daemon=True).start()
    
    def get_headers(self):
        """Retorna headers para requisições autenticadas"""
        return {
            "X-Emby-Token": self.access_token,
            "X-Emby-Authorization": f'MediaBrowser Client="Jellyfin Downloader", Device="Python", DeviceId="{self.device_id}", Version="1.0.0"'
        }
    
    def load_series(self):
        """Carrega lista de séries"""
        if not self.access_token:
            messagebox.showwarning("Aviso", "Faça login primeiro!")
            return
        
        self.status_label.config(text="📡 Carregando séries...")
        self.progress.config(mode="indeterminate")
        self.progress.start()
        
        def fetch_series():
            try:
                url = f"{self.server_url}/Users/{self.user_id}/Items"
                headers = self.get_headers()
                params = {
                    "IncludeItemTypes": "Series",
                    "Recursive": "true",
                    "Fields": "Overview,SortName,ProductionYear",
                    "SortBy": "SortName",
                    "SortOrder": "Ascending"
                }
                
                response = requests.get(url, headers=headers, params=params, timeout=20)
                
                if response.status_code == 200:
                    data = response.json()
                    self.series_data = data.get("Items", [])
                    
                    self.root.after(0, self.update_series_tree)
                    self.root.after(0, lambda: self.status_label.config(text=f"✅ {len(self.series_data)} séries carregadas"))
                else:
                    self.root.after(0, lambda: messagebox.showerror("Erro", f"Erro ao carregar séries: {response.status_code}"))
                    self.root.after(0, lambda: self.status_label.config(text="❌ Erro ao carregar"))
                
                self.root.after(0, self.progress.stop)
                self.root.after(0, lambda: self.progress.config(mode="determinate"))
                
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("Erro", f"Erro: {str(e)}"))
                self.root.after(0, lambda: self.status_label.config(text="❌ Erro"))
                self.root.after(0, self.progress.stop)
        
        threading.Thread(target=fetch_series, daemon=True).start()
    
    def filter_series(self, event=None):
        """Filtra séries por nome"""
        search_term = self.search_entry.get().lower()
        
        # Limpa tree
        for item in self.series_tree.get_children():
            self.series_tree.delete(item)
        
        # Filtra e adiciona séries
        filtered = [s for s in self.series_data if search_term in s.get("Name", "").lower()]
        
        for series in filtered:
            name = series.get("Name", "Sem nome")
            year = series.get("ProductionYear", "")
            series_id = series.get("Id")
            
            info = f"Ano: {year}" if year else "Ano desconhecido"
            
            self.series_tree.insert("", "end", iid=series_id, text="📺", values=(name, info, "Clique 2x para ver episódios"))
    
    def update_series_tree(self):
        """Atualiza árvore de séries"""
        self.filter_series()
    
    def on_item_double_click(self, event):
        """Ao clicar duas vezes em um item"""
        selection = self.series_tree.selection()
        if not selection:
            return
        
        item_id = selection[0]
        parent = self.series_tree.parent(item_id)
        grandparent = self.series_tree.parent(parent)
        
        if not parent:  # É uma série
            self.load_episodes(item_id)
        elif not grandparent:  # É uma temporada
            self.download_season(item_id)
        else:  # É um episódio
            self.queue_download_episode(item_id)
    
    def load_episodes_from_menu(self):
        """Carrega episódios do menu de contexto"""
        selection = self.series_tree.selection()
        if selection:
            item_id = selection[0]
            parent = self.series_tree.parent(item_id)
            if not parent:
                self.load_episodes(item_id)
    
    def load_episodes(self, series_id):
        """Carrega episódios de uma série"""
        self.status_label.config(text="📡 Carregando episódios...")
        self.progress.config(mode="indeterminate")
        self.progress.start()
        
        def fetch_episodes():
            try:
                url = f"{self.server_url}/Shows/{series_id}/Episodes"
                headers = self.get_headers()
                params = {
                    "UserId": self.user_id,
                    "Fields": "Path,MediaSources,Overview"
                }
                
                response = requests.get(url, headers=headers, params=params, timeout=20)
                
                if response.status_code == 200:
                    data = response.json()
                    episodes = data.get("Items", [])
                    
                    # Remove episódios anteriores
                    for child in self.series_tree.get_children(series_id):
                        self.series_tree.delete(child)
                    
                    # Agrupa por temporada
                    seasons = {}
                    for ep in episodes:
                        season_num = ep.get("ParentIndexNumber", 0)
                        if season_num not in seasons:
                            seasons[season_num] = []
                        seasons[season_num].append(ep)
                    
                    # Adiciona temporadas e episódios
                    for season_num in sorted(seasons.keys()):
                        season_id = f"{series_id}_season_{season_num}"
                        season_episodes = seasons[season_num]
                        
                        self.root.after(0, lambda sid=series_id, ssid=season_id, sn=season_num, count=len(season_episodes):
                                      self.series_tree.insert(sid, "end", iid=ssid, text="📁",
                                                            values=(f"Temporada {sn}", f"{count} episódios", "Clique 2x para baixar todos")))
                        
                        for ep in season_episodes:
                            ep_name = ep.get("Name", "Sem nome")
                            season = ep.get("ParentIndexNumber", 0)
                            episode = ep.get("IndexNumber", 0)
                            ep_id = ep.get("Id")
                            
                            display_name = f"E{episode:02d} - {ep_name}"
                            
                            # Verifica se já foi baixado
                            safe_series = "".join(c for c in self.series_tree.item(series_id)["values"][0] if c.isalnum() or c in (' ', '-', '_')).strip()
                            safe_ep = "".join(c for c in ep_name if c.isalnum() or c in (' ', '-', '_')).strip()
                            filename = f"{safe_series} - S{season:02d}E{episode:02d} - {safe_ep}.mp4"
                            series_folder = os.path.join(self.download_path, safe_series)
                            filepath = os.path.join(series_folder, filename)
                            
                            status = "✅ Já baixado" if os.path.exists(filepath) else "⬇️ Pronto para baixar"
                            
                            self.root.after(0, lambda ssid=season_id, eid=ep_id, dn=display_name, st=status:
                                          self.series_tree.insert(ssid, "end", iid=eid, text="🎬", values=(dn, "", st)))
                    
                    self.root.after(0, lambda: self.series_tree.item(series_id, open=True))
                    self.root.after(0, lambda: self.status_label.config(text=f"✅ {len(episodes)} episódios carregados"))
                else:
                    self.root.after(0, lambda: messagebox.showerror("Erro", f"Erro ao carregar episódios: {response.status_code}"))
                
                self.root.after(0, self.progress.stop)
                self.root.after(0, lambda: self.progress.config(mode="determinate"))
                
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("Erro", f"Erro: {str(e)}"))
                self.root.after(0, self.progress.stop)
        
        threading.Thread(target=fetch_episodes, daemon=True).start()
    
    def download_selected(self):
        """Baixa item selecionado"""
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
            # Temporada
            self.download_season(item_id)
        else:
            # Episódio
            self.queue_download_episode(item_id)
    
    def download_season(self, season_id=None):
        """Baixa temporada completa"""
        if not season_id:
            selection = self.series_tree.selection()
            if not selection:
                messagebox.showwarning("Aviso", "Selecione uma temporada!")
                return
            season_id = selection[0]
        
        # Pega todos os episódios da temporada
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
        
        for ep_id in to_download:
            self.queue_download_episode(ep_id, show_success=False)
    
    def queue_download_episode(self, episode_id, show_success=True):
        """Adiciona episódio à fila de download"""
        current_status = self.series_tree.item(episode_id)["values"][2]
        
        if "✅" in current_status:
            if show_success:
                messagebox.showinfo("Info", "Este episódio já foi baixado!")
            return
        
        self.root.after(0, lambda: self.series_tree.item(episode_id, values=(
            self.series_tree.item(episode_id)["values"][0],
            "",
            "🔄 Preparando..."
        )))
        
        def fetch_meta_and_queue():
            try:
                # Busca metadados com tamanho
                url = f"{self.server_url}/Users/{self.user_id}/Items/{episode_id}"
                headers = self.get_headers()
                params = {
                    "Fields": "MediaSources"
                }
                response = requests.get(url, headers=headers, params=params, timeout=15)
                
                if response.status_code != 200:
                    raise Exception(f"Erro ao buscar metadados: {response.status_code}")
                
                data = response.json()
                series_name = data.get("SeriesName", "Serie")
                season = data.get("ParentIndexNumber", 0)
                episode = data.get("IndexNumber", 0)
                ep_name = data.get("Name", "Episodio")
                
                # Obtém tamanho do arquivo da API
                media_sources = data.get('MediaSources', [{}])
                total_size = media_sources[0].get('Size', 0) if media_sources else 0
                
                # Nome do arquivo limpo
                safe_series = "".join(c for c in series_name if c.isalnum() or c in (' ', '-', '_')).strip()
                safe_ep = "".join(c for c in ep_name if c.isalnum() or c in (' ', '-', '_')).strip()
                filename = f"{safe_series} - S{season:02d}E{episode:02d} - {safe_ep}.mp4"
                
                # Cria pasta da série
                series_folder = os.path.join(self.download_path, safe_series)
                os.makedirs(series_folder, exist_ok=True)
                
                filepath = os.path.join(series_folder, filename)
                
                if os.path.exists(filepath):
                    self.root.after(0, lambda: self.series_tree.item(episode_id, values=(
                        self.series_tree.item(episode_id)["values"][0], "", "✅ Já existe"
                    )))
                    return
                
                # URL de download
                download_url = f"{self.server_url}/Videos/{episode_id}/stream.mp4"
                
                # Headers otimizados
                download_headers = headers.copy()
                download_headers.update({
                    'Accept-Encoding': 'identity',
                    'Connection': 'keep-alive'
                })
                
                self.download_items[episode_id] = {
                    'filename': filename,
                    'filepath': filepath,
                    'download_url': download_url,
                    'total_size': total_size,
                    'downloaded': 0,
                    'progress_var': tk.DoubleVar(value=0),
                    'status_var': tk.StringVar(value="Na fila"),
                    'speed_var': tk.StringVar(value="0 MB/s"),
                    'eta_var': tk.StringVar(value=""),
                    'start_time': None,
                    'last_downloaded': 0,
                    'last_time': time.time()
                }
                
                self.root.after(0, lambda: self.series_tree.item(episode_id, values=(
                    self.series_tree.item(episode_id)["values"][0],
                    "",
                    "🔄 Na fila"
                )))
                
                self.download_queue.put((episode_id, show_success))
                self.update_queue_status()
                
            except Exception as e:
                self.root.after(0, lambda: self.series_tree.item(episode_id, values=(
                    self.series_tree.item(episode_id)["values"][0], "", "❌ Erro"
                )))
                self.root.after(0, lambda: messagebox.showerror("Erro", f"Erro ao preparar: {str(e)}"))
        
        threading.Thread(target=fetch_meta_and_queue, daemon=True).start()
    
    def download_episode_core(self, episode_id, show_success):
        """Baixa um episódio (lógica principal)"""
        if episode_id not in self.download_items:
            return
        
        item = self.download_items[episode_id]
        item['status_var'].set("Baixando")
        item['start_time'] = time.time()
        item['last_time'] = item['start_time']
        item['last_downloaded'] = 0
        
        self.root.after(0, lambda: self.series_tree.item(episode_id, values=(
            self.series_tree.item(episode_id)["values"][0],
            "",
            "⬇️ Baixando..."
        )))
        
        try:
            download_headers = self.get_headers()
            download_headers.update({
                'Accept-Encoding': 'identity',
                'Connection': 'keep-alive'
            })
            
            with requests.get(item['download_url'], headers=download_headers, stream=True, timeout=30) as r:
                r.raise_for_status()
                total_size = item['total_size']
                # Se API não forneceu, tenta do header
                if total_size == 0:
                    total_size = int(r.headers.get('content-length', 0))
                    item['total_size'] = total_size
                
                with open(item['filepath'], 'wb') as f:
                    downloaded = 0
                    chunk_size = 1024 * 1024  # 1MB
                    update_interval = 5 * 1024 * 1024  # Atualiza a cada 5MB
                    
                    for chunk in r.iter_content(chunk_size=chunk_size):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            item['downloaded'] = downloaded
                            
                            current_time = time.time()
                            elapsed = current_time - item['last_time']
                            
                            if elapsed >= 1.0:
                                speed = (downloaded - item['last_downloaded']) / elapsed / 1024 / 1024
                                percent = (downloaded / total_size) * 100 if total_size > 0 else 0
                                mb_downloaded = downloaded / 1024 / 1024
                                mb_total = total_size / 1024 / 1024
                                eta = ((total_size - downloaded) / (speed * 1024 * 1024)) if speed > 0 and total_size > 0 else 0
                                
                                info_text = f"{percent:.1f}% | {speed:.2f} MB/s | {mb_downloaded:.1f}/{mb_total:.1f} MB | ETA: {eta:.0f}s" if total_size > 0 else f"{mb_downloaded:.1f} MB baixados | {speed:.2f} MB/s"
                                
                                self.root.after(0, lambda it=info_text: self.series_tree.item(episode_id, values=(
                                    self.series_tree.item(episode_id)["values"][0],
                                    it,
                                    "⬇️ Baixando..."
                                )))
                                
                                item['progress_var'].set(percent)
                                item['speed_var'].set(f"{speed:.2f} MB/s")
                                item['eta_var'].set(f"{eta:.0f}s" if total_size > 0 else "Desconhecido")
                                
                                item['last_time'] = current_time
                                item['last_downloaded'] = downloaded
            
            # Após o download, força 100%
            if item['total_size'] > 0:
                item['downloaded'] = item['total_size']
            else:
                item['total_size'] = downloaded
            percent = 100
            item['progress_var'].set(percent)
            item['speed_var'].set("0.00 MB/s")
            item['eta_var'].set("0s")
            item['status_var'].set("Concluído")
            
            mb_downloaded = item['downloaded'] / (1024 * 1024)
            mb_total = item['total_size'] / (1024 * 1024)
            info_text = f"100% | 0.00 MB/s | {mb_downloaded:.1f}/{mb_total:.1f} MB | ETA: 0s"
            
            self.root.after(0, lambda it=info_text: self.series_tree.item(episode_id, values=(
                self.series_tree.item(episode_id)["values"][0],
                it,
                "✅ Concluído"
            )))
            self.root.after(0, lambda: self.status_label.config(text=f"✅ Download concluído: {item['filename']}"))
            
            if show_success:
                self.root.after(0, lambda: messagebox.showinfo("Sucesso", f"Episódio baixado!\n\n{item['filepath']}"))
                
        except Exception as e:
            item['status_var'].set("Erro")
            self.root.after(0, lambda: self.series_tree.item(episode_id, values=(
                self.series_tree.item(episode_id)["values"][0], "", "❌ Erro"
            )))
            self.root.after(0, lambda: messagebox.showerror("Erro", f"Erro ao baixar: {str(e)}"))
            self.root.after(0, lambda: self.status_label.config(text="❌ Erro no download"))
    
    def open_download_manager(self):
        """Abre janela de gerenciamento de downloads"""
        if self.manager_window and self.manager_window.winfo_exists():
            self.manager_window.lift()
            return
        
        self.manager_window = tk.Toplevel(self.root)
        self.manager_window.title("Gerenciador de Downloads")
        self.manager_window.geometry("800x600")
        self.manager_window.protocol("WM_DELETE_WINDOW", self.close_manager)
        
        # Canvas para scroll
        canvas = tk.Canvas(self.manager_window)
        scrollbar = ttk.Scrollbar(self.manager_window, orient="vertical", command=canvas.yview)
        self.scrollable_frame = ttk.Frame(canvas)
        
        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(
                scrollregion=canvas.bbox("all")
            )
        )
        
        canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Progresso total
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
        
        # Linha de downloads
        self.download_rows = {}
        
        self.update_manager()
    
    def update_manager(self):
        if not self.manager_window or not self.manager_window.winfo_exists():
            return
        
        # Adiciona novas rows
        for ep_id, item in list(self.download_items.items()):
            if ep_id not in self.download_rows:
                row_frame = ttk.LabelFrame(self.scrollable_frame, text=item['filename'], padding=5)
                row_frame.pack(fill="x", pady=5, padx=10)
                
                prog_frame = ttk.Frame(row_frame)
                prog_frame.pack(fill="x")
                
                prog = ttk.Progressbar(prog_frame, variable=item['progress_var'], maximum=100, length=200)
                prog.pack(side="left", fill="x", expand=True, padx=5)
                
                percent_label = ttk.Label(prog_frame, text="0%")
                def update_percent(*args):
                    percent = item['progress_var'].get()
                    percent_label.config(text=f"{percent:.1f}%" if item['total_size'] > 0 else "Desconhecido")
                item['progress_var'].trace("w", update_percent)
                percent_label.pack(side="left", padx=5)
                
                ttk.Label(row_frame, text="Velocidade:").pack(side="left", padx=5)
                ttk.Label(row_frame, textvariable=item['speed_var']).pack(side="left", padx=5)
                
                ttk.Label(row_frame, text="ETA:").pack(side="left", padx=5)
                ttk.Label(row_frame, textvariable=item['eta_var']).pack(side="left", padx=5)
                
                ttk.Label(row_frame, text="Status:").pack(side="left", padx=5)
                ttk.Label(row_frame, textvariable=item['status_var']).pack(side="left", padx=5)
                
                self.download_rows[ep_id] = row_frame
        
        # Atualiza total
        total_downloaded = sum(i['downloaded'] for i in self.download_items.values())
        total_size = sum(i['total_size'] for i in self.download_items.values())
        
        if total_size > 0:
            percent = (total_downloaded / total_size) * 100
            self.total_progress_var.set(percent)
            self.total_percent_var.set(f"{percent:.1f}%")
        else:
            self.total_progress_var.set(0)
            self.total_percent_var.set("0%")
        
        # Velocidade total: soma das velocidades
        total_speed = 0.0
        for i in self.download_items.values():
            try:
                total_speed += float(i['speed_var'].get().split()[0])
            except:
                pass
        self.total_speed_var.set(f"{total_speed:.2f} MB/s")
        
        self.manager_window.after(1000, self.update_manager)
    
    def close_manager(self):
        self.manager_window.destroy()
        self.manager_window = None
    
def main():
    root = tk.Tk()
    
    # Estilo
    style = ttk.Style()
    style.theme_use('clam')
    
    app = JellyfinDownloader(root)
    root.mainloop()
if __name__ == "__main__":
    main()