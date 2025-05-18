import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import subprocess
import threading
import sys
import queue
import time
from datetime import datetime
import os
from PIL import Image, ImageTk
import base64
import io
import signal
import glob
from dotenv import load_dotenv
import json
import hashlib
import requests
import socket
import uuid

# Constantes para ícones
ICON_SIZE = (24, 24)  # Tamanho padrão dos ícones
ICONS_PATH = "assets"  # Pasta onde os ícones serão armazenados

def load_and_resize_image(image_path):
    """
    Carrega e redimensiona uma imagem para o tamanho padrão de ícone.
    Retorna None silenciosamente se a imagem não for encontrada.
    """
    try:
        if not os.path.exists(image_path):
            return None
            
        # Abrir e redimensionar a imagem
        with Image.open(image_path) as img:
            img = img.resize(ICON_SIZE, Image.Resampling.LANCZOS)
            return ImageTk.PhotoImage(img)
    except Exception:
        return None

class ModernButton(ttk.Button):
    def __init__(self, master, **kwargs):
        # Configurar estilo
        style = ttk.Style()
        style.configure('Default.TButton',
                       font=('Segoe UI', 9),
                       padding=(10, 5))
                       
        style.configure('Action.TButton',
                       font=('Segoe UI', 9),
                       padding=(10, 5))
                       
        # Definir estilo baseado no tipo de botão
        if kwargs.get('text') in ["Iniciar", "Parar", "Reiniciar"]:
            kwargs['style'] = 'Action.TButton'
        else:
            kwargs['style'] = 'Default.TButton'
            
        # Processar ícone
        self.icon_image = None
        if 'icon' in kwargs:
            icon_path = kwargs.pop('icon')
            if icon_path:
                full_path = os.path.join(ICONS_PATH, icon_path)
                self.icon_image = load_and_resize_image(full_path)
                if self.icon_image:
                    kwargs['image'] = self.icon_image
                    kwargs['compound'] = 'left'
        
        super().__init__(master, **kwargs)

class ConfigWindow:
    def __init__(self, parent):
        self.window = tk.Toplevel(parent)
        self.window.title("Configurações")
        self.window.geometry("500x500")
        self.window.resizable(False, False)
        
        # Dicionário com as descrições dos campos
        self.field_info = {
            # Admin Config
            'ADMIN_ID': 'ID do administrador do bot no Discord',
            'DISCORD_TOKEN': 'Token de autenticação do bot no Discord',
            'STEAM_API_KEY': 'Chave da API Steam para consulta de informações',
            
            # Canais Config
            'REGISTERED_ROLE_ID': 'ID do cargo atribuído aos usuários registrados',
            'REGISTRATION_CHANNEL_ID': 'ID do canal onde o registro será realizado',
            'ADMIN_CHANNEL_ID': 'ID do canal para comandos administrativos',
            'SALES_CONFIRMATION_CHANNEL_ID': 'ID do canal para confirmação de vendas',
            
            # Server Config
            'BANK_FILE': 'Caminho para o arquivo de banco de dados',
            'BALANCE_KEY': 'Chave para consulta de saldo no banco de dados'
        }
        
        # Carregar configurações atuais
        load_dotenv()
        
        # Frame principal
        main_frame = ttk.Frame(self.window, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Título
        title_label = ttk.Label(
            main_frame,
            text="Configurações do Bot",
            font=('Segoe UI', 12, 'bold')
        )
        title_label.pack(pady=(0, 10))
        
        # Criar notebook para as abas
        notebook = ttk.Notebook(main_frame)
        notebook.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # Criar frames para cada aba
        admin_frame = ttk.Frame(notebook, padding=10)
        channels_frame = ttk.Frame(notebook, padding=10)
        server_frame = ttk.Frame(notebook, padding=10)
        
        # Adicionar abas ao notebook
        notebook.add(admin_frame, text="Admin Config")
        notebook.add(channels_frame, text="Canais Config")
        notebook.add(server_frame, text="Server Config")
        
        # Configurações e seus campos
        self.config_vars = {
            # Admin Config
            'ADMIN_ID': tk.StringVar(value=os.getenv('ADMIN_ID', '')),
            'DISCORD_TOKEN': tk.StringVar(value=os.getenv('DISCORD_TOKEN', '')),
            'STEAM_API_KEY': tk.StringVar(value=os.getenv('STEAM_API_KEY', '')),
            
            # Canais Config
            'REGISTERED_ROLE_ID': tk.StringVar(value=os.getenv('REGISTERED_ROLE_ID', '')),
            'REGISTRATION_CHANNEL_ID': tk.StringVar(value=os.getenv('REGISTRATION_CHANNEL_ID', '')),
            'ADMIN_CHANNEL_ID': tk.StringVar(value=os.getenv('ADMIN_CHANNEL_ID', '')),
            'SALES_CONFIRMATION_CHANNEL_ID': tk.StringVar(value=os.getenv('SALES_CONFIRMATION_CHANNEL_ID', '')),
            
            # Server Config
            'BANK_FILE': tk.StringVar(value=os.getenv('BANK_FILE', '')),
            'BALANCE_KEY': tk.StringVar(value=os.getenv('BALANCE_KEY', 'Balance'))
        }
        
        # Criar campos para Admin Config
        admin_fields = ['ADMIN_ID', 'DISCORD_TOKEN', 'STEAM_API_KEY']
        self._create_fields(admin_frame, admin_fields)
        
        # Criar campos para Canais Config
        channel_fields = ['REGISTERED_ROLE_ID', 'REGISTRATION_CHANNEL_ID', 'ADMIN_CHANNEL_ID', 'SALES_CONFIRMATION_CHANNEL_ID']
        self._create_fields(channels_frame, channel_fields)
        
        # Criar campos para Server Config
        server_fields = ['BANK_FILE', 'BALANCE_KEY']
        self._create_fields(server_frame, server_fields)
        
        # Frame para botões
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=10)
        
        # Botões
        ttk.Button(
            button_frame,
            text="Salvar",
            command=self.save_config,
            style='Action.TButton'
        ).pack(side=tk.RIGHT, padx=5)
        
        ttk.Button(
            button_frame,
            text="Cancelar",
            command=self.window.destroy,
            style='Default.TButton'
        ).pack(side=tk.RIGHT)
        
        # Centralizar a janela
        self.window.transient(parent)
        self.window.grab_set()
        parent.wait_window(self.window)
    
    def _create_fields(self, parent_frame, field_list):
        """Cria campos de entrada para uma lista de configurações"""
        for row, key in enumerate(field_list):
            # Frame para cada campo
            field_frame = ttk.Frame(parent_frame)
            field_frame.grid(row=row, column=0, columnspan=2, sticky='ew', pady=5)
            
            # Label do campo
            label = ttk.Label(field_frame, text=key)
            label.pack(anchor='w')
            
            # Descrição do campo
            desc_label = ttk.Label(
                field_frame,
                text=self.field_info[key],
                font=('Segoe UI', 8),
                foreground='gray'
            )
            desc_label.pack(anchor='w', padx=(10, 0))
            
            # Entry
            entry = ttk.Entry(field_frame, textvariable=self.config_vars[key], width=40)
            entry.pack(fill='x', padx=(0, 5), pady=(2, 0))
            
        # Configurar expansão da coluna
        parent_frame.grid_columnconfigure(1, weight=1)
        
    def save_config(self):
        try:
            # Ler conteúdo atual do .env
            env_content = {}
            if os.path.exists('.env'):
                with open('.env', 'r', encoding='utf-8') as f:
                    for line in f:
                        if '=' in line:
                            key, value = line.strip().split('=', 1)
                            env_content[key] = value
            
            # Atualizar com novos valores no .env
            for key, var in self.config_vars.items():
                value = var.get().strip()
                if value:
                    env_content[key] = value
            
            # Salvar no arquivo .env
            with open('.env', 'w', encoding='utf-8') as f:
                for key, value in env_content.items():
                    f.write(f"{key}={value}\n")

            # Atualizar config.json
            config_data = {}
            if os.path.exists('config.json'):
                try:
                    with open('config.json', 'r', encoding='utf-8') as f:
                        config_data = json.load(f)
                except json.JSONDecodeError:
                    pass

            # Mapear campos do .env para config.json
            env_to_config_map = {
                'ADMIN_CHANNEL_ID': 'admin_channel_id',
                'REGISTRATION_CHANNEL_ID': 'registration_channel_id',
                'REGISTERED_ROLE_ID': 'registered_role_id',
                'SALES_CONFIRMATION_CHANNEL_ID': 'sales_confirmation_channel_id'
            }

            # Atualizar valores no config_data
            for env_key, config_key in env_to_config_map.items():
                if env_key in self.config_vars:
                    value = self.config_vars[env_key].get().strip()
                    if value:
                        try:
                            # Tentar converter para número se possível
                            config_data[config_key] = int(value)
                        except ValueError:
                            config_data[config_key] = value

            # Salvar no config.json
            with open('config.json', 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=4)
            
            messagebox.showinfo("Sucesso", "Configurações salvas com sucesso!\nReinicie o bot para aplicar as alterações.")
            self.window.destroy()
            
        except Exception as e:
            messagebox.showerror("Erro", f"Erro ao salvar configurações: {str(e)}")

class LicenseManager:
    def __init__(self):
        self.license_url = "https://raw.githubusercontent.com/DayZprojectFM/ProjetoFM/refs/heads/main/botdiscord.Json"
        self.installation_path = os.path.abspath(os.path.dirname(__file__))
        self.license_code = self._generate_license_code()
        
    def _generate_license_code(self):
        """Gera um código único baseado em características do sistema"""
        # Combina caminho de instalação, hostname e MAC address
        system_info = [
            self.installation_path,
            socket.gethostname(),
            ':'.join(['{:02x}'.format((uuid.getnode() >> elements) & 0xff) 
                     for elements in range(0,2*6,2)][::-1])
        ]
        
        # Cria um hash único
        combined_info = '_'.join(system_info).encode('utf-8')
        return hashlib.sha256(combined_info).hexdigest()[:32]
    
    def verify_license(self):
        """Verifica se a licença é válida"""
        try:
            response = requests.get(self.license_url)
            if response.status_code == 200:
                license_data = response.json()
                for entry in license_data:
                    if entry.get("code") == self.license_code:
                        return True, "Licença válida"
                return False, "Licença inválida"
            return False, "Erro ao verificar licença"
        except Exception as e:
            return False, f"Erro na verificação: {str(e)}"

class AboutWindow:
    def __init__(self, parent):
        self.window = tk.Toplevel(parent)
        self.window.title("Sobre")
        self.window.geometry("400x400")
        self.window.resizable(False, False)
        
        # Encontrar a instância principal do BotGUI
        for widget in parent.winfo_children():
            if isinstance(widget, ttk.Frame):
                self.main_app = widget.master
                break
        
        # Configurar tema
        style = ttk.Style()
        style.configure('About.TLabel', font=('Segoe UI', 9))
        style.configure('AboutTitle.TLabel', font=('Segoe UI', 14, 'bold'))
        
        # Frame principal com padding
        main_frame = ttk.Frame(self.window, padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Título
        ttk.Label(
            main_frame,
            text="Discord Steam Bot",
            style='AboutTitle.TLabel'
        ).pack(pady=(0, 10))
        
        # Versão
        ttk.Label(
            main_frame,
            text="Versão 1.0.0",
            style='About.TLabel'
        ).pack(pady=(0, 20))
        
        # Desenvolvedor
        dev_frame = ttk.LabelFrame(main_frame, text="Desenvolvedor", padding=10)
        dev_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(
            dev_frame,
            text="Desenvolvido por FMJ_Delta",
            style='About.TLabel'
        ).pack(expand=True)
        
        # Contato
        contact_frame = ttk.LabelFrame(main_frame, text="Contato", padding=10)
        contact_frame.pack(fill=tk.X, pady=(0, 10))
        
        discord_link = tk.Label(
            contact_frame,
            text="https://discord.gg/zrT9D5bkqz",
            fg="blue",
            cursor="hand2",
            font=('Segoe UI', 9, 'underline')
        )
        discord_link.pack(expand=True)
        discord_link.bind("<Button-1>", lambda e: self.open_link("https://discord.gg/zrT9D5bkqz"))
        
        # Licença
        try:
            license_frame = ttk.LabelFrame(main_frame, text="Licença", padding=10)
            license_frame.pack(fill=tk.X, pady=(0, 10))
            
            # Obter o código da licença diretamente da instância principal
            if hasattr(self.main_app, 'license_manager'):
                license_code = self.main_app.license_manager.license_code
            else:
                # Criar uma nova instância do LicenseManager se necessário
                license_manager = LicenseManager()
                license_code = license_manager.license_code
            
            # Criar e configurar o campo de licença
            license_entry = ttk.Entry(license_frame, width=40)
            license_entry.insert(0, license_code)
            license_entry.configure(state='readonly')
            license_entry.pack(pady=5, expand=True)
            
        except Exception as e:
            print(f"Erro ao criar frame de licença: {e}")
            # Adicionar um label de erro para feedback visual
            ttk.Label(
                main_frame,
                text="Erro ao carregar código de licença",
                foreground="red",
                style='About.TLabel'
            ).pack(pady=5)
        
        # Botão Fechar
        ttk.Button(
            main_frame,
            text="Fechar",
            command=self.window.destroy,
            style='Default.TButton'
        ).pack(pady=(10, 0))
        
        # Centralizar a janela em relação ao parent
        self.window.transient(parent)
        self.window.grab_set()
        
        # Calcular posição para centralizar
        window_width = 400
        window_height = 400
        screen_width = parent.winfo_screenwidth()
        screen_height = parent.winfo_screenheight()
        
        x = parent.winfo_x() + (parent.winfo_width() - window_width) // 2
        y = parent.winfo_y() + (parent.winfo_height() - window_height) // 2
        
        # Garantir que a janela fique dentro da tela
        x = max(0, min(x, screen_width - window_width))
        y = max(0, min(y, screen_height - window_height))
        
        self.window.geometry(f"{window_width}x{window_height}+{x}+{y}")
        
        # Aguardar a janela ser fechada
        parent.wait_window(self.window)
    
    def open_link(self, url):
        """Abre o link no navegador padrão"""
        import webbrowser
        webbrowser.open(url)

class BotGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Discord Steam Bot - Registro Steam ")
        self.root.geometry("500x350")
        
        # Inicializar gerenciador de licença
        self.license_manager = LicenseManager()
        
        # Configurar tema Windows
        style = ttk.Style()
        style.theme_use('vista' if os.name == 'nt' else 'clam')
        
        try:
            icon_image = load_and_resize_image("assets/icon.png")
            if icon_image:
                self.root.iconphoto(True, icon_image)
        except Exception:
            pass
        
        # Frame principal
        self.main_frame = ttk.Frame(self.root)
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Frame superior com data e hora
        self.top_frame = ttk.Frame(self.main_frame)
        self.top_frame.pack(fill=tk.X, padx=2, pady=(0, 5))
        
        # Label para data
        self.date_label = ttk.Label(
            self.top_frame,
            font=('Segoe UI', 9),
            text=""
        )
        self.date_label.pack(side=tk.LEFT)
        
        # Label para hora
        self.time_label = ttk.Label(
            self.top_frame,
            font=('Segoe UI', 9),
            text=""
        )
        self.time_label.pack(side=tk.RIGHT)
        
        # Separador horizontal
        self.separator = ttk.Separator(self.main_frame, orient='horizontal')
        self.separator.pack(fill=tk.X, padx=2, pady=5)
        
        # Status do Bot e Licença
        self.status_frame = ttk.Frame(self.main_frame)
        self.status_frame.pack(fill=tk.X, padx=2, pady=2)
        
        self.status_label = ttk.Label(
            self.status_frame,
            text="Status: Offline",
            font=('Segoe UI', 9)
        )
        self.status_label.pack(side=tk.LEFT)
        
        self.license_label = ttk.Label(
            self.status_frame,
            text="Licença: Verificando...",
            font=('Segoe UI', 9)
        )
        self.license_label.pack(side=tk.RIGHT)
        
        # Área de Logs
        self.log_frame = ttk.LabelFrame(self.main_frame, text="Logs", padding=5)
        self.log_frame.pack(fill=tk.BOTH, expand=True, padx=2, pady=5)
        
        self.log_text = scrolledtext.ScrolledText(
            self.log_frame,
            wrap=tk.WORD,
            font=('Consolas', 9),
            height=10
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)
        
        # Frame de Botões
        self.button_frame = ttk.Frame(self.main_frame)
        self.button_frame.pack(fill=tk.X, padx=2, pady=5)
        
        # Botões
        button_configs = [
            {
                'text': "Iniciar",
                'command': self.start_bot,
                'icon': 'start.png',
                'side': tk.LEFT,
                'width': 12
            },
            {
                'text': "Parar",
                'command': self.stop_bot,
                'state': tk.DISABLED,
                'icon': 'stop.png',
                'side': tk.LEFT,
                'width': 12
            },
            {
                'text': "Reiniciar",
                'command': self.restart_bot,
                'state': tk.DISABLED,
                'icon': 'restart.png',
                'side': tk.LEFT,
                'width': 12
            },
            {
                'text': "Limpar Logs",
                'command': self.clear_logs,
                'icon': 'clear.png',
                'side': tk.RIGHT,
                'width': 12
            }
        ]
        
        # Criar botões
        for config in button_configs:
            side = config.pop('side')
            btn = ModernButton(self.button_frame, **config)
            btn.pack(side=side, padx=3, pady=2)
            
            # Armazenar referências dos botões
            if config['text'] == "Iniciar":
                self.start_button = btn
            elif config['text'] == "Parar":
                self.stop_button = btn
            elif config['text'] == "Reiniciar":
                self.restart_button = btn
            else:
                self.clear_button = btn
        
        # Variáveis de controle
        self.bot_process = None
        self.output_queue = queue.Queue()
        self.running = True
        
        # Iniciar thread de atualização dos logs
        self.update_thread = threading.Thread(target=self.update_logs)
        self.update_thread.daemon = True
        self.update_thread.start()
        
        # Configurar fechamento da janela
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        # Configurar limpeza automática de backups
        self.cleanup_backups()
        
        # Configurar menu
        self.setup_menu()
    
    def setup_menu(self):
        """Configura a barra de menu"""
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        
        # Menu Arquivo
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Arquivo", menu=file_menu)
        file_menu.add_command(label="Sair", command=self.on_closing)
        
        # Menu Configurações
        config_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Configurações", menu=config_menu)
        config_menu.add_command(label="Configurar Bot", command=self.open_config)
        
        # Menu Informações
        info_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Informações", menu=info_menu)
        info_menu.add_command(label="Sobre", command=self.open_about)
    
    def open_config(self):
        """Abre a janela de configurações"""
        ConfigWindow(self.root)
    
    def open_about(self):
        """Abre a janela Sobre"""
        AboutWindow(self.root)
    
    def verify_and_update_license(self):
        """Verifica a licença e atualiza a interface"""
        is_valid, message = self.license_manager.verify_license()
        self.license_label.config(
            text=f"Licença: {message}",
            foreground="green" if is_valid else "red"
        )
        
        # Habilitar/desabilitar botão de início baseado na licença
        self.start_button.configure(state=tk.NORMAL if is_valid else tk.DISABLED)
        
        if not is_valid:
            messagebox.showwarning(
                "Licença Inválida",
                "Este bot não está licenciado para uso neste computador.\n" +
                "Entre em contato com o desenvolvedor para obter uma licença."
            )
    
    def update_status(self, status):
        self.status_label.configure(text=f"Status: {status}")
    
    def log(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.output_queue.put(f"[{timestamp}] {message}\n")
    
    def update_logs(self):
        while self.running:
            try:
                while True:
                    message = self.output_queue.get_nowait()
                    self.log_text.configure(state='normal')
                    self.log_text.insert(tk.END, message)
                    self.log_text.see(tk.END)
                    self.log_text.configure(state='disabled')
            except queue.Empty:
                time.sleep(0.1)
    
    def start_bot(self):
        try:
            self.start_button.configure(state=tk.DISABLED)
            self.stop_button.configure(state=tk.NORMAL)
            self.restart_button.configure(state=tk.NORMAL)
            
            self.update_status("Iniciando...")
            self.log("Iniciando bot...")
            
            # Configurar ambiente
            env = os.environ.copy()
            env['PYTHONIOENCODING'] = 'utf-8'
            
            # Configurações para esconder console
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            
            # Iniciar o bot sem console
            self.bot_process = subprocess.Popen(
                ['pythonw', 'bot.py'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                universal_newlines=True,
                startupinfo=startupinfo,
                creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
                env=env,
                encoding='utf-8'
            )
            
            threading.Thread(target=self.read_output, args=(self.bot_process.stdout,), daemon=True).start()
            threading.Thread(target=self.read_output, args=(self.bot_process.stderr,), daemon=True).start()
            
            self.update_status("Online")
            
        except Exception as e:
            self.log(f"Erro ao iniciar bot: {str(e)}")
            self.start_button.configure(state=tk.NORMAL)
            self.stop_button.configure(state=tk.DISABLED)
            self.restart_button.configure(state=tk.DISABLED)
            self.update_status("Erro")
    
    def stop_bot(self):
        try:
            if self.bot_process:
                self.bot_process.terminate()
                self.bot_process = None
                self.log("Bot finalizado.")
                
            self.start_button.configure(state=tk.NORMAL)
            self.stop_button.configure(state=tk.DISABLED)
            self.restart_button.configure(state=tk.DISABLED)
            self.update_status("Offline")
            
            # Limpar backups ao parar o bot
            self.cleanup_backups()
            
        except Exception as e:
            self.log(f"Erro ao parar bot: {str(e)}")
    
    def restart_bot(self):
        try:
            self.log("Reiniciando bot...")
            self.update_status("Reiniciando...")
            
            if self.bot_process:
                self.bot_process.terminate()
                self.bot_process = None
            
            # Limpar logs antes de reiniciar
            self.clear_logs()
            self.log("Reiniciando bot...")
            
            time.sleep(2)
            
            # Configurar ambiente
            env = os.environ.copy()
            env['PYTHONIOENCODING'] = 'utf-8'
            
            # Configurações para esconder console
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            
            # Iniciar o bot sem console
            self.bot_process = subprocess.Popen(
                ['pythonw', 'bot.py'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                universal_newlines=True,
                startupinfo=startupinfo,
                creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
                env=env,
                encoding='utf-8'
            )
            
            threading.Thread(target=self.read_output, args=(self.bot_process.stdout,), daemon=True).start()
            threading.Thread(target=self.read_output, args=(self.bot_process.stderr,), daemon=True).start()
            
            self.update_status("Online")
            self.log("Bot reiniciado com sucesso!")
            
        except Exception as e:
            self.log(f"Erro ao reiniciar bot: {str(e)}")
            self.update_status("Erro")
            self.start_button.configure(state=tk.NORMAL)
            self.stop_button.configure(state=tk.DISABLED)
            self.restart_button.configure(state=tk.DISABLED)
    
    def read_output(self, pipe):
        for line in pipe:
            if self.running:
                self.output_queue.put(line)
    
    def clear_logs(self):
        self.log_text.configure(state='normal')
        self.log_text.delete(1.0, tk.END)
        self.log_text.configure(state='disabled')
        self.log("Logs limpos.")
    
    def cleanup_backups(self):
        """Limpa arquivos de backup antigos (.bak)"""
        try:
            # Procura por todos os arquivos .bak
            backup_files = glob.glob("*.bak.*")
            for file in backup_files:
                try:
                    os.remove(file)
                    self.log(f"Arquivo de backup removido: {file}")
                except Exception as e:
                    self.log(f"Erro ao remover arquivo de backup {file}: {e}")
        except Exception as e:
            self.log(f"Erro ao limpar arquivos de backup: {e}")
    
    def on_closing(self):
        self.running = False
        if self.bot_process:
            try:
                # Tenta finalizar o processo do bot graciosamente
                self.bot_process.terminate()
                # Espera até 5 segundos pelo processo terminar
                try:
                    self.bot_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    # Se não terminar em 5 segundos, força o encerramento
                    self.bot_process.kill()
                
                # Garante que todos os processos filhos também sejam finalizados
                if os.name == 'nt':  # Windows
                    subprocess.run(['taskkill', '/F', '/T', '/PID', str(self.bot_process.pid)], 
                                 startupinfo=subprocess.STARTUPINFO(dwFlags=subprocess.STARTF_USESHOWWINDOW))
                else:  # Linux/Mac
                    os.killpg(os.getpgid(self.bot_process.pid), signal.SIGTERM)
                
                self.bot_process = None
                print("Bot finalizado com sucesso.")
                
                # Limpar backups antes de fechar
                self.cleanup_backups()
                
            except Exception as e:
                print(f"Erro ao finalizar bot: {e}")
        
        # Finaliza a janela
        self.root.destroy()
        # Garante que o programa seja completamente encerrado
        os._exit(0)
    
    def update_datetime(self):
        """Atualiza a data e hora na interface"""
        # Formatar data e hora em português
        now = datetime.now()
        date_str = now.strftime("%d/%m/%Y")
        time_str = now.strftime("%H:%M:%S")
        
        # Atualizar labels
        self.date_label.config(text=f"Data: {date_str}")
        self.time_label.config(text=f"Hora: {time_str}")
        
        # Agendar próxima atualização em 1 segundo
        self.root.after(1000, self.update_datetime)

    def run(self):
        self.log("Interface iniciada. Verificando licença...")
        # Verificar licença antes de permitir o uso
        self.verify_and_update_license()
        # Iniciar atualização de data e hora
        self.update_datetime()
        self.root.mainloop()

if __name__ == "__main__":
    # Esconder console principal
    if os.name == 'nt':
        import ctypes
        ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)
    
    gui = BotGUI()
    gui.run() 
