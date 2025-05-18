import os
import discord
from discord.ext import commands
from discord import app_commands
import aiosqlite
import aiohttp
from dotenv import load_dotenv
import re
from datetime import datetime
import json
import asyncio
from collections import deque
from time import time
import shutil
import traceback

# Carrega as variáveis de ambiente
load_dotenv()

# Dicionário para armazenar locks de arquivos
file_locks = {}

# Cache para evitar processamento duplicado
processed_files = {}

async def get_file_lock(file_path):
    """Obtém um lock para um arquivo específico"""
    if file_path not in file_locks:
        file_locks[file_path] = asyncio.Lock()
    return file_locks[file_path]

def create_backup(file_path):
    """Cria um backup do arquivo com timestamp"""
    try:
        # Verificar se é um arquivo de teste (ID = 0)
        if os.path.basename(file_path).startswith('0.json'):
            print("Arquivo de teste detectado, ignorando backup")
            return None
            
        backup_path = f"{file_path}.bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        shutil.copy2(file_path, backup_path)
        print(f"Backup criado: {backup_path}")
        return backup_path
    except Exception as e:
        print(f"Erro ao criar backup: {e}")
        return None

def validate_json_structure(data):
    """Valida a estrutura básica do arquivo JSON"""
    required_fields = ['purchase', 'user', 'delivered_products']
    missing_fields = [field for field in required_fields if field not in data]
    
    if missing_fields:
        print(f"Campos obrigatórios ausentes: {', '.join(missing_fields)}")
        return False
    return True

# Carrega as variáveis de ambiente
CONFIG_FILE = 'config.json'

# Rate Limiting para API Steam
class SteamRateLimiter:
    def __init__(self, requests_per_second=1):
        self.requests_per_second = requests_per_second
        self.requests = deque()
        
    async def acquire(self):
        now = time()
        
        # Remove requisições antigas (mais de 1 segundo)
        while self.requests and self.requests[0] < now - 1:
            self.requests.popleft()
        
        # Se atingiu o limite, espera
        if len(self.requests) >= self.requests_per_second:
            wait_time = self.requests[0] - (now - 1)
            if wait_time > 0:
                await asyncio.sleep(wait_time)
        
        # Adiciona nova requisição
        self.requests.append(now)

# Criar instância global do rate limiter
steam_rate_limiter = SteamRateLimiter()

def load_config():
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except:
        # Usar valores do .env como padrão
        config = {
            'registration_channel_id': os.getenv('REGISTRATION_CHANNEL_ID'),
            'registered_role_id': os.getenv('REGISTERED_ROLE_ID'),
            'sales_confirmation_channel_id': os.getenv('SALES_CONFIRMATION_CHANNEL_ID', None)
        }
        save_config(config)
        return config

def save_config(config):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=4)

def get_channel_id():
    config = load_config()
    return int(config.get('registration_channel_id') or os.getenv('REGISTRATION_CHANNEL_ID'))

def get_role_id():
    config = load_config()
    return int(config.get('registered_role_id') or os.getenv('REGISTERED_ROLE_ID'))

def get_sales_confirmation_channel_id():
    config = load_config()
    return int(config.get('sales_confirmation_channel_id')) if config.get('sales_confirmation_channel_id') else None

# Configuração do bot
intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents)

# Regex para validar URL da Steam
STEAM_PROFILE_REGEX = r'(?:https?:\/\/)?steamcommunity\.com\/(?:profiles\/[0-9]+|id\/[\w-]+)'

class SteamLinkModal(discord.ui.Modal, title='Vincular Conta Steam'):
    def __init__(self, is_update=False):
        super().__init__()
        self.is_update = is_update
        
    steam_url = discord.ui.TextInput(
        label='Link do Perfil Steam',
        placeholder='https://steamcommunity.com/id/seunome',
        required=True,
        min_length=10,
        max_length=100
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        # Validar formato da URL
        if not re.match(STEAM_PROFILE_REGEX, str(self.steam_url)):
            await interaction.followup.send(
                "❌ Link inválido! Por favor, use um link válido do Steam.\n"
                "Exemplos:\n"
                "- https://steamcommunity.com/id/seunome\n"
                "- https://steamcommunity.com/profiles/76561198xxxxxxxxx\n"
                "Certifique-se de copiar o link completo do seu perfil.",
                ephemeral=True
            )
            return

        await interaction.followup.send("🔍 Verificando seu perfil Steam... Por favor, aguarde.", ephemeral=True)
        steam_id = await get_steam_id64(str(self.steam_url))

        if not steam_id:
            await interaction.followup.send(
                "❌ Não foi possível verificar seu perfil da Steam. Certifique-se de que:\n"
                "1. O link está correto e completo\n"
                "2. O perfil existe\n"
                "3. Você copiou o link diretamente do seu perfil Steam\n\n"
                "Dica: Abra seu perfil Steam no navegador e copie a URL completa.",
                ephemeral=True
            )
            return

        # Buscar dados do perfil
        profile_data = await get_steam_profile_data(steam_id)
        if not profile_data:
            await interaction.followup.send(
                "❌ Não foi possível obter os dados do perfil. Erro ao acessar a API da Steam.",
                ephemeral=True
            )
            return

        # Criar embed com os dados do perfil
        embed = discord.Embed(
            title="Confirmar Perfil Steam",
            description="Por favor, confirme se este é seu perfil Steam:",
            color=discord.Color.blue()
        )
        
        embed.add_field(name="Nome Steam", value=profile_data.get('personaname', 'N/A'), inline=True)
        embed.add_field(name="Steam ID", value=steam_id, inline=True)
        
        if profile_data.get('profileurl'):
            embed.add_field(name="Link do Perfil", value=profile_data['profileurl'], inline=False)
        
        # Status do perfil
        visibility = "Público" if profile_data.get('communityvisibilitystate', 1) == 3 else "Privado/Limitado"
        embed.add_field(name="Visibilidade", value=visibility, inline=True)
        
        # Status online
        status_map = {
            0: "Offline",
            1: "Online",
            2: "Ocupado",
            3: "Ausente",
            4: "Dormindo",
            5: "Trocando",
            6: "Jogando"
        }
        status = status_map.get(profile_data.get('personastate', 0), "Desconhecido")
        embed.add_field(name="Status", value=status, inline=True)
        
        if profile_data.get('avatarfull'):
            embed.set_thumbnail(url=profile_data['avatarfull'])

        # Criar view com botões de confirmação
        view = ConfirmationView(steam_id, profile_data, self.is_update)
        message = await interaction.followup.send(
            embed=embed,
            view=view,
            ephemeral=True
        )
        view.message = message

class ConfirmationView(discord.ui.View):
    def __init__(self, steam_id: str, profile_data: dict, is_update: bool = False):
        super().__init__(timeout=180)  # 3 minutos de timeout
        self.steam_id = steam_id
        self.profile_data = profile_data
        self.is_update = is_update

    @discord.ui.button(label="Confirmar", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Salvar/Atualizar no banco de dados
        async with aiosqlite.connect('users.db') as db:
            await db.execute(
                'INSERT OR REPLACE INTO users (discord_id, discord_name, steam_id) VALUES (?, ?, ?)',
                (str(interaction.user.id), interaction.user.name, self.steam_id)
            )
            await db.commit()

        # Adicionar cargo de registro
        registered_role = interaction.guild.get_role(get_role_id())
        if registered_role:
            await interaction.user.add_roles(registered_role)
            action = "atualizada" if self.is_update else "vinculada"
            await interaction.response.edit_message(
                content=f"✅ Conta Steam {action} com sucesso!\n"
                f"Steam ID: {self.steam_id}\n"
                f"Cargo {registered_role.mention} {'mantido' if self.is_update else 'adicionado'}!",
                view=None,
                embed=None
            )
        else:
            await interaction.response.edit_message(
                content="⚠️ Registro concluído, mas não foi possível gerenciar o cargo (cargo não encontrado).",
                view=None,
                embed=None
            )

    @discord.ui.button(label="Alterar", style=discord.ButtonStyle.primary)
    async def change(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = SteamLinkModal(self.is_update)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="❌ Verificação cancelada.",
            view=None,
            embed=None
        )

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        try:
            await self.message.edit(
                content="⏰ Tempo expirado. Por favor, inicie o processo novamente.",
                view=self
            )
        except:
            pass

class RegistrationSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label="Registrar",
                description="Vincular sua conta Steam",
                emoji="🟢",
                value="register"
            ),
            discord.SelectOption(
                label="Consultar Cadastro",
                description="Ver sua conta vinculada",
                emoji="🔵",
                value="check"
            ),
            discord.SelectOption(
                label="Alterar Conta Steam",
                description="Mudar sua conta Steam",
                emoji="⚫",
                value="change"
            ),
            discord.SelectOption(
                label="Remover Cadastro",
                description="Desvincular sua conta",
                emoji="🔴",
                value="remove"
            )
        ]
        super().__init__(
            placeholder="Selecione uma ação...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        try:
            # Verificar registro existente para opções que requerem cadastro
            if self.values[0] in ["check", "change", "remove"]:
                async with aiosqlite.connect('users.db') as db:
                    cursor = await db.execute('SELECT steam_id FROM users WHERE discord_id = ?', (str(interaction.user.id),))
                    existing_user = await cursor.fetchone()
                    
                if not existing_user:
                    await interaction.response.send_message(
                        "❌ Você não possui uma conta Steam vinculada. Use a opção 'Registrar' primeiro.",
                        ephemeral=True
                    )
                    return

            # Processar cada opção
            if self.values[0] == "register":
                # Verificar permissões antes de prosseguir
                registered_role = interaction.guild.get_role(get_role_id())
                if registered_role:
                    has_perm, message = await check_role_permissions(interaction.guild, interaction.guild.me, registered_role)
                    if not has_perm:
                        await interaction.response.send_message(
                            f"⚠️ {message}\nPor favor, contate um administrador do servidor.",
                            ephemeral=True
                        )
                        return

                # Verificar se já tem registro
                async with aiosqlite.connect('users.db') as db:
                    cursor = await db.execute('SELECT steam_id FROM users WHERE discord_id = ?', (str(interaction.user.id),))
                    existing_user = await cursor.fetchone()
                    
                if existing_user:
                    await interaction.response.send_message(
                        "Você já possui uma conta Steam vinculada. Use a opção 'Alterar Conta Steam' se desejar fazer alterações.",
                        ephemeral=True
                    )
                    return

                modal = SteamLinkModal()
                await interaction.response.send_modal(modal)

            elif self.values[0] == "check":
                async with aiosqlite.connect('users.db') as db:
                    cursor = await db.execute('SELECT steam_id FROM users WHERE discord_id = ?', (str(interaction.user.id),))
                    user_data = await cursor.fetchone()
                    
                steam_id = user_data[0]
                profile_data = await get_steam_profile_data(steam_id)

                if not profile_data:
                    await interaction.response.send_message(
                        "❌ Não foi possível obter os dados atualizados do seu perfil Steam.",
                        ephemeral=True
                    )
                    return

                embed = discord.Embed(
                    title="Seu Perfil Steam Vinculado",
                    description="Estes são os dados do seu perfil Steam atual:",
                    color=discord.Color.blue()
                )
                embed.add_field(name="Nome Steam", value=profile_data.get('personaname', 'N/A'), inline=True)
                embed.add_field(name="Steam ID", value=steam_id, inline=True)
                if profile_data.get('avatarfull'):
                    embed.set_thumbnail(url=profile_data['avatarfull'])

                await interaction.response.send_message(embed=embed, ephemeral=True)

            elif self.values[0] == "change":
                modal = SteamLinkModal(is_update=True)
                await interaction.response.send_modal(modal)

            elif self.values[0] == "remove":
                try:
                    # Verificar permissões antes de prosseguir
                    registered_role = interaction.guild.get_role(get_role_id())
                    if not registered_role:
                        await interaction.response.send_message(
                            "❌ Erro: Cargo de registro não encontrado. Verifique a configuração do REGISTERED_ROLE_ID.",
                            ephemeral=True
                        )
                        return

                    # Debug: Imprimir informações detalhadas
                    print(f"\nInformações de Remoção de Cargo:")
                    print(f"Usuário: {interaction.user.name} (ID: {interaction.user.id})")
                    print(f"Cargo a remover: {registered_role.name} (ID: {registered_role.id})")
                    print(f"Bot tem admin: {interaction.guild.me.guild_permissions.administrator}")
                    print(f"Cargos do usuário: {[r.name for r in interaction.user.roles]}")
                    print(f"Cargo está no usuário: {registered_role in interaction.user.roles}")
                    
                    # Verificar permissões do bot
                    has_perm, perm_message = await check_role_permissions(interaction.guild, interaction.guild.me, registered_role)
                    if not has_perm:
                        await interaction.response.send_message(
                            f"❌ Erro de permissões: {perm_message}\nPor favor, contate um administrador do servidor.",
                            ephemeral=True
                        )
                        return

                    # Remover do banco de dados primeiro
                    async with aiosqlite.connect('users.db') as db:
                        await db.execute('DELETE FROM users WHERE discord_id = ?', (str(interaction.user.id),))
                        await db.commit()

                    # Tentar remover o cargo usando a função segura
                    success, message = await remove_role_safely(interaction.user, registered_role)
                    
                    if success:
                        await interaction.response.send_message(
                            f"✅ Cadastro removido com sucesso!\n{message}",
                            ephemeral=True
                        )
                    else:
                        await interaction.response.send_message(
                            f"✅ Cadastro removido do banco de dados!\n⚠️ {message}\n" +
                            "Recomendações:\n" +
                            "1. Verifique se o cargo do bot está acima do cargo a ser removido\n" +
                            "2. Certifique-se que o bot tem todas as permissões necessárias\n" +
                            "3. O cargo não deve ser gerenciado por integração",
                            ephemeral=True
                        )

                except Exception as e:
                    print(f"Erro geral na função remove: {str(e)}")
                    await interaction.response.send_message(
                        f"❌ Erro ao remover cadastro: {str(e)}",
                        ephemeral=True
                    )

        except Exception as e:
            # Se algo der errado, tentar enviar uma mensagem de erro
            try:
                await interaction.response.send_message(
                    f"❌ Ocorreu um erro ao processar sua solicitação: {str(e)}",
                    ephemeral=True
                )
            except:
                # Se já respondeu, usar followup
                await interaction.followup.send(
                    f"❌ Ocorreu um erro ao processar sua solicitação: {str(e)}",
                    ephemeral=True
                )

class RegistrationView(discord.ui.View):
    def __init__(self):
        super().__init__()
        self.add_item(RegistrationSelect())

class AdminSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label="Estatísticas",
                description="Ver dados gerais do sistema",
                emoji="📊",
                value="stats"
            ),
            discord.SelectOption(
                label="Exportar Dados",
                description="Baixar CSV com todos os registros",
                emoji="📥",
                value="export"
            ),
            discord.SelectOption(
                label="Canal de Registro",
                description="Configurar canal do sistema",
                emoji="⚙️",
                value="channel"
            ),
            discord.SelectOption(
                label="Canal de Confirmação de Vendas",
                description="Configurar canal para confirmação de vendas",
                emoji="📡",
                value="sales_confirmation"
            )
        ]
        super().__init__(
            placeholder="Selecione uma ação administrativa...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        if self.values[0] == "sales_confirmation":
            current_channel = interaction.guild.get_channel(get_sales_confirmation_channel_id() or 0)
            current_status = f"Canal atual: {current_channel.mention if current_channel else 'Não configurado'}"
            
            embed = discord.Embed(
                title="📡 Configuração do Canal de Confirmação de Vendas",
                description=(
                    f"{current_status}\n\n"
                    "Selecione abaixo o novo canal de confirmação de vendas.\n"
                    "O bot irá processar as confirmações de vendas neste canal."
                ),
                color=discord.Color.blue()
            )
            
            # Criar view para seleção de canal
            class SalesConfirmationChannelSelect(discord.ui.ChannelSelect):
                def __init__(self):
                    super().__init__(placeholder="Selecione o canal...")

                async def callback(self, interaction: discord.Interaction):
                    channel = self.values[0]
                    config = load_config()
                    config['sales_confirmation_channel_id'] = str(channel.id)
                    save_config(config)
                    
                    await interaction.response.send_message(
                        f"✅ Canal de confirmação de vendas configurado para {channel.mention}",
                        ephemeral=True
                    )

            view = discord.ui.View()
            view.add_item(SalesConfirmationChannelSelect())
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            
        elif self.values[0] == "stats":
            async with aiosqlite.connect('users.db') as db:
                cursor = await db.execute('SELECT COUNT(*) FROM users')
                total_users = (await cursor.fetchone())[0]
                
                cursor = await db.execute('''
                    SELECT discord_name, steam_id 
                    FROM users 
                    ORDER BY ROWID DESC 
                    LIMIT 5
                ''')
                recent_users = await cursor.fetchall()

            embed = discord.Embed(
                title="📊 Estatísticas do Sistema",
                description="Informações sobre o sistema de verificação",
                color=discord.Color.blue(),
                timestamp=datetime.now()
            )
            
            embed.add_field(
                name="Total de Usuários Verificados",
                value=f"🔰 {total_users} usuários",
                inline=False
            )
            
            if recent_users:
                recent_list = "\n".join([f"• {name} (Steam: {steam_id})" for name, steam_id in recent_users])
                embed.add_field(
                    name="Últimos Registros",
                    value=recent_list,
                    inline=False
                )
            
            await interaction.followup.send(embed=embed, ephemeral=True)

        elif self.values[0] == "export":
            async with aiosqlite.connect('users.db') as db:
                cursor = await db.execute('SELECT discord_id, discord_name, steam_id FROM users')
                users = await cursor.fetchall()
            
            if not users:
                await interaction.followup.send("❌ Não há dados para exportar.", ephemeral=True)
                return
            
            csv_content = "Discord ID,Discord Name,Steam ID\n"
            csv_content += "\n".join([f"{user[0]},{user[1]},{user[2]}" for user in users])
            
            with open("users_export.csv", "w", encoding="utf-8") as f:
                f.write(csv_content)
            
            await interaction.followup.send(
                "✅ Dados exportados com sucesso!",
                file=discord.File("users_export.csv"),
                ephemeral=True
            )
            
            os.remove("users_export.csv")

        elif self.values[0] == "channel":
            current_channel = interaction.guild.get_channel(get_channel_id())
            current_status = f"Canal atual: {current_channel.mention if current_channel else 'Não configurado'}"
            
            embed = discord.Embed(
                title="⚙️ Configuração do Canal de Registro",
                description=(
                    f"{current_status}\n\n"
                    "Selecione abaixo o novo canal de registro.\n"
                    "Os menus de registro serão automaticamente movidos para o novo canal."
                ),
                color=discord.Color.blue()
            )
            
            view = ConfigView('channel')
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)

class AdminView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(AdminSelect())

class ConfigView(discord.ui.View):
    def __init__(self, config_type: str):
        super().__init__()
        self.config_type = config_type
        
        # Adicionar seletor de canal
        channel_select = discord.ui.ChannelSelect(
            placeholder="Selecione o canal...",
            channel_types=[discord.ChannelType.text]
        )
        channel_select.callback = self.channel_callback
        self.add_item(channel_select)
    
    async def channel_callback(self, interaction: discord.Interaction):
        try:
            channel = interaction.data['values'][0]
            config = load_config()
            
            if self.config_type == 'channel':
                config['registration_channel_id'] = channel
                await interaction.response.send_message(
                    f"✅ Canal de registro configurado para <#{channel}>",
                    ephemeral=True
                )
                # Configurar o novo canal
                new_channel = interaction.guild.get_channel(int(channel))
                if new_channel:
                    await setup_registration_channel(interaction.client)
            
            save_config(config)
            
        except Exception as e:
            await interaction.response.send_message(
                f"❌ Erro ao configurar canal: {str(e)}",
                ephemeral=True
            )

async def setup_database():
    async with aiosqlite.connect('users.db') as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                discord_id TEXT PRIMARY KEY,
                discord_name TEXT,
                steam_id TEXT
            )
        ''')
        await db.commit()

async def get_steam_id64(profile_url: str) -> str:
    # Limpar a URL
    profile_url = profile_url.strip().rstrip('/')
    
    try:
        # Tentar extrair steamid64 diretamente da URL de perfil numérico
        if 'profiles/' in profile_url:
            steam_id = profile_url.split('profiles/')[-1].split('/')[0]
            if steam_id.isdigit() and len(steam_id) == 17:
                return steam_id
        
        # Tentar extrair vanity URL
        if 'id/' in profile_url:
            vanity_url = profile_url.split('id/')[-1].split('/')[0]
        else:
            # Se não encontrou "id/", usa a última parte da URL
            vanity_url = profile_url.split('/')[-1]
        
        # Aguardar rate limit antes de fazer a requisição
        await steam_rate_limiter.acquire()
        
        # Tentar resolver vanity URL via API
        async with aiohttp.ClientSession() as session:
            api_url = f'http://api.steampowered.com/ISteamUser/ResolveVanityURL/v0001/?key={os.getenv("STEAM_API_KEY")}&vanityurl={vanity_url}'
            async with session.get(api_url) as response:
                if response.status == 429:  # Too Many Requests
                    print("Rate limit atingido. Aguardando 2 segundos...")
                    await asyncio.sleep(2)  # Espera 2 segundos
                    return await get_steam_id64(profile_url)  # Tenta novamente
                    
                if response.status == 200:
                    data = await response.json()
                    if data['response'].get('success') == 1:
                        return data['response']['steamid']
                    
        # Se chegou aqui, tentar uma última vez com a URL completa
        await steam_rate_limiter.acquire()
        
        async with aiohttp.ClientSession() as session:
            api_url = f'http://api.steampowered.com/ISteamUser/ResolveVanityURL/v0001/?key={os.getenv("STEAM_API_KEY")}&vanityurl={profile_url}'
            async with session.get(api_url) as response:
                if response.status == 429:  # Too Many Requests
                    print("Rate limit atingido. Aguardando 2 segundos...")
                    await asyncio.sleep(2)  # Espera 2 segundos
                    return await get_steam_id64(profile_url)  # Tenta novamente
                    
                if response.status == 200:
                    data = await response.json()
                    if data['response'].get('success') == 1:
                        return data['response']['steamid']
    
    except Exception as e:
        print(f"Erro ao obter Steam ID: {e}")
    
    return None

async def get_steam_profile_data(steam_id: str) -> dict:
    try:
        # Aguardar rate limit antes de fazer a requisição
        await steam_rate_limiter.acquire()
        
        async with aiohttp.ClientSession() as session:
            api_url = f'http://api.steampowered.com/ISteamUser/GetPlayerSummaries/v0002/?key={os.getenv("STEAM_API_KEY")}&steamids={steam_id}'
            async with session.get(api_url) as response:
                if response.status == 429:  # Too Many Requests
                    print("Rate limit atingido. Aguardando 2 segundos...")
                    await asyncio.sleep(2)  # Espera 2 segundos
                    return await get_steam_profile_data(steam_id)  # Tenta novamente
                    
                if response.status != 200:
                    print(f"Erro na API Steam: Status {response.status}")
                    return None
                
                data = await response.json()
                if not data.get('response', {}).get('players'):
                    return None
                
                player = data['response']['players'][0]
                
                # Criar dicionário com dados básicos (sempre disponíveis)
                profile_data = {
                    'steamid': player.get('steamid'),
                    'personaname': player.get('personaname', 'Nome não disponível'),
                    'avatarfull': player.get('avatarfull'),
                    'profileurl': player.get('profileurl'),
                    'personastate': player.get('personastate', 0),
                }
                
                # Adicionar dados extras se o perfil for público
                if player.get('communityvisibilitystate', 1) == 3:  # 3 = Público
                    profile_data.update({
                        'realname': player.get('realname'),
                        'timecreated': player.get('timecreated'),
                        'loccountrycode': player.get('loccountrycode'),
                        'gameextrainfo': player.get('gameextrainfo'),
                    })
                
                return profile_data
                
    except Exception as e:
        print(f"Erro ao obter dados do perfil Steam: {e}")
        return None

async def setup_registration_channel(bot):
    try:
        channel = bot.get_channel(get_channel_id())
        if channel:
            await channel.purge()
            
            embed = discord.Embed(
                title="Sistema de Registro Steam",
                description=(
                    "Bem-vindo ao sistema de registro Steam!\n\n"
                    "Use o menu abaixo para:\n"
                    "🟢 **Registrar**: Vincular sua conta Steam\n"
                    "🔵 **Consultar Cadastro**: Ver sua conta vinculada\n"
                    "⚫ **Alterar Conta Steam**: Mudar sua conta Steam\n"
                    "🔴 **Remover Cadastro**: Desvincular sua conta"
                ),
                color=discord.Color.blue()
            )
            await channel.send(embed=embed, view=RegistrationView())
            print("Menu de registro configurado com sucesso!")
    except Exception as e:
        print(f"Erro ao configurar canal de registro: {e}")

@bot.event
async def on_ready():
    print(f'Bot está online como {bot.user.name}')
    
    # Configurar presença do bot
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="registros Steam"
        ),
        status=discord.Status.online
    )
    
    await setup_database()
    
    # Verificar permissões do bot
    for guild in bot.guilds:
        registered_role = guild.get_role(get_role_id())
        if registered_role:
            has_perm, message = await check_role_permissions(guild, guild.me, registered_role)
            if not has_perm:
                print(f"⚠️ Aviso de permissões no servidor {guild.name}: {message}")
    
    # Registrar comandos de aplicação
    try:
        synced = await bot.tree.sync()
        print(f"Sincronizados {len(synced)} comandos")
    except Exception as e:
        print(f"Erro ao sincronizar comandos: {e}")
    
    # Configurar canal de registro
    await setup_registration_channel(bot)
    
    # Configurar canal administrativo
    try:
        admin_channel = bot.get_channel(int(os.getenv('ADMIN_CHANNEL_ID')))
        if admin_channel:
            await admin_channel.purge()
            
            # Verificar permissões antes de configurar
            registered_role = admin_channel.guild.get_role(get_role_id())
            if registered_role:
                has_perm, message = await check_role_permissions(admin_channel.guild, admin_channel.guild.me, registered_role)
                if not has_perm:
                    embed = discord.Embed(
                        title="⚠️ Aviso de Permissões",
                        description=message,
                        color=discord.Color.yellow()
                    )
                    await admin_channel.send(embed=embed)
            
            embed = discord.Embed(
                title="🔐 Painel Administrativo",
                description=(
                    "Bem-vindo ao painel administrativo!\n\n"
                    "Use o menu abaixo para acessar as funções:\n"
                    "📊 **Estatísticas**: Ver dados gerais do sistema\n"
                    "📥 **Exportar Dados**: Baixar CSV com todos os registros\n"
                    "⚙️ **Canal de Registro**: Configurar canal do sistema\n"
                    "📡 **Canal de Confirmação de Vendas**: Configurar canal de vendas"
                ),
                color=discord.Color.dark_gold()
            )
            await admin_channel.send(embed=embed, view=AdminView())
            print("Painel administrativo configurado com sucesso!")
    except Exception as e:
        print(f"Erro ao configurar painel administrativo: {e}")

async def get_user_info(db, discord_id=None, discord_name=None):
    try:
        if discord_id:
            cursor = await db.execute(
                'SELECT * FROM users WHERE discord_id = ?',
                (str(discord_id),)
            )
            result = await cursor.fetchone()
            if result:
                return {
                    'discord_id': result[0],
                    'discord_name': result[1],
                    'steam_id': result[2]
                }

        if discord_name:
            cursor = await db.execute(
                'SELECT * FROM users WHERE discord_name = ?',
                (discord_name,)
            )
            result = await cursor.fetchone()
            if result:
                return {
                    'discord_id': result[0],
                    'discord_name': result[1],
                    'steam_id': result[2]
                }

        return None
    except Exception as e:
        return None

async def process_sale_embed(message: discord.Message):
    try:
        if not message.embeds:
            return

        embed = message.embeds[0]
        if not embed.fields:
            return

        # Extrair informações do embed
        pedido_id = None
        discord_info = None
        valor = None

        for field in embed.fields:
            if 'Pedido' in field.name:
                pedido_id = field.value
            elif 'Discord' in field.name:
                discord_info = field.value
            elif 'Valor' in field.name:
                valor = field.value

        if not all([pedido_id, discord_info]):
            return

        # Extrair Discord ID
        discord_id = None
        if '<@' in discord_info:
            discord_id = extract_discord_id(discord_info)
        else:
            # Tentar encontrar o ID no texto
            discord_id = extract_discord_id(discord_info)

        if not discord_id:
            return

        # Buscar usuário no Discord
        user = message.guild.get_member(int(discord_id))
        if not user:
            return

        total_users = 0
        async with aiosqlite.connect('users.db') as db:
            cursor = await db.execute('SELECT COUNT(*) FROM users')
            result = await cursor.fetchone()
            total_users = result[0] if result else 0

            if user:
                user_info = await get_user_info(db, discord_id=user.id)
                if user_info:
                    return user_info

            # Se não encontrou por ID, tentar por nome
            if not user_info:
                user_info = await get_user_info(db, discord_name=user.name)
                if user_info:
                    return user_info

        return {
            'discord_id': str(user.id),
            'discord_name': user.name,
            'steam_id': None
        }

    except Exception as error:
        return None

class SalesConfirmationChannel:
    def __init__(self, channel_id: int):
        self.channel_id = channel_id
        self.log_file = 'vendas_confirmacao.log'
        
        # Carregar e validar o caminho do BANK_FILE
        bank_file = os.getenv('BANK_FILE')
        if not bank_file:
            print("⚠️ BANK_FILE não configurado no arquivo .env")
            self.bank_file_path = None
            return
            
        # Tratar caminho de rede (UNC path)
        if bank_file.startswith('\\\\'):
            # Preservar o formato UNC e garantir barras duplas
            self.bank_file_path = bank_file
            if not self.bank_file_path.endswith('\\'):
                self.bank_file_path += '\\'
            print(f"Caminho de rede detectado: {self.bank_file_path}")
        else:
            # Para caminhos locais, usar normalização padrão
            self.bank_file_path = os.path.normpath(bank_file)
            print(f"Caminho local detectado: {self.bank_file_path}")
        
        try:
            # Tentar acessar o diretório
            print(f"Tentando acessar diretório: {self.bank_file_path}")
            if not os.path.exists(self.bank_file_path):
                print(f"⚠️ Caminho do BANK_FILE não encontrado ou sem acesso: {self.bank_file_path}")
                print("Verifique se:")
                print("1. O caminho está correto")
                print("2. O computador tem acesso à rede")
                print("3. As permissões de acesso estão corretas")
                self.bank_file_path = None
                return
                
            print(f"✅ BANK_FILE configurado e com acesso: {self.bank_file_path}")
                
        except Exception as e:
            print(f"⚠️ Erro ao acessar BANK_FILE: {str(e)}")
            self.bank_file_path = None
            return
            
        # Garantir que o arquivo de log existe
        self._create_log_file()

    def _create_log_file(self):
        try:
            # Verifica se o arquivo existe, se não, cria
            if not os.path.exists(self.log_file):
                with open(self.log_file, 'w', encoding='utf-8') as f:
                    f.write("=== Arquivo de Log de Vendas ===\n")
                print(f"Arquivo de log criado: {self.log_file}")
        except Exception as e:
            print(f"Erro ao criar arquivo de log: {e}")

    async def get_steam_id(self, user_id: str) -> str:
        try:
            async with aiosqlite.connect('users.db') as db:
                cursor = await db.execute('SELECT steam_id FROM users WHERE discord_id = ?', (user_id,))
                result = await cursor.fetchone()
                if result and result[0]:
                    return result[0]
                return "Usuário não registrado"
        except Exception as e:
            print(f"Erro ao buscar Steam ID: {e}")
            return "Erro ao buscar registro"
            
    async def process_json_file(self, attachment: discord.Attachment) -> bool:
        try:
            print(f"\nIniciando processamento do arquivo: {attachment.filename}")
            print(f"Tamanho do arquivo: {attachment.size} bytes")
            
            # Validar tamanho máximo (1MB)
            if attachment.size > 1024 * 1024:
                print("❌ Arquivo muito grande (limite: 1MB)")
                return False
                
            # Verifica se é um arquivo JSON
            if not attachment.filename.endswith('.json'):
                print(f"❌ Arquivo ignorado: {attachment.filename} (não é JSON)")
                return False
                
            # Baixa o conteúdo do arquivo
            json_content = await attachment.read()
            json_text = json_content.decode('utf-8')  # Converte bytes para string
            
            try:
                data = json.loads(json_text)
            except json.JSONDecodeError as e:
                print(f"❌ Erro ao decodificar JSON: {e}")
                print(f"Conteúdo problemático: {json_text[:200]}...")  # Mostra primeiros 200 caracteres
                return False
            
            # Valida estrutura do JSON
            if not validate_json_structure(data):
                print("❌ Estrutura JSON inválida")
                return False
            
            # Extrai o ID da compra e verifica se já foi processado
            purchase_id = data.get('purchase', {}).get('id', 'N/A')
            user_id = data.get('user', {}).get('id', 'N/A')
            
            # Se não for um arquivo de teste (purchase ID != 0), verifica duplicidade
            if purchase_id != '0' and is_file_processed(purchase_id):
                print(f"⚠️ Arquivo já processado anteriormente: Purchase ID {purchase_id}")
                return False
                
            print(f"✅ Arquivo JSON válido: {attachment.filename}")
            
            # Processa o conteúdo do novo formato
            valor_total = 0
            codigos = []
            valores_processados = set()  # Para evitar duplicação
            
            # Processa delivered_products
            delivered_products = data.get('delivered_products', [])
            print("\nProcessando produtos entregues:")
            
            for product in delivered_products:
                print(f"\nProduto ID: {product.get('id')}")
                content = product.get('content', [])
                
                for item in content:
                    if item.get('type') == 'number':
                        try:
                            valor = int(item.get('value', 0))
                            item_id = f"{product.get('id')}_{item.get('id')}"
                            
                            if valor > 0 and item_id not in valores_processados:
                                print(f"✅ Valor válido encontrado: {valor}")
                                valor_total += valor
                                valores_processados.add(item_id)
                            else:
                                print(f"⚠️ Valor ignorado: {valor} (valor <= 0 ou já processado)")
                        except (ValueError, TypeError) as e:
                            print(f"❌ Valor inválido ignorado: {item.get('value')} - Erro: {e}")
                
                content_raw = product.get('content_raw')
                if content_raw:
                    codigos.append(content_raw)
                    print(f"Código adicionado: {content_raw[:10]}...")
            
            # Busca o Steam ID do usuário
            steam_id = await self.get_steam_id(user_id)
            
            print(f"\nResumo do processamento:")
            print(f"Purchase ID: {purchase_id}")
            print(f"User ID: {user_id}")
            print(f"Steam ID: {steam_id}")
            print(f"Valor Total: {valor_total}")
            print(f"Quantidade de Códigos: {len(codigos)}")
            
            # Cria o registro de log
            log_entry = {
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'purchase_id': purchase_id,
                'user_id': user_id,
                'steam_id': steam_id,
                'valor_total': valor_total,
                'codigos': codigos,
                'valores_processados': list(valores_processados)  # Adiciona lista de valores processados ao log
            }
            
            # Salva no arquivo de log
            await self._save_log(log_entry)
            
            # Marca o arquivo como processado apenas se não for teste (purchase ID != 0)
            if purchase_id != '0':
                mark_file_processed(purchase_id)
            
            print(f"✅ Log salvo com sucesso para Purchase ID: {purchase_id}")
            return True
            
        except Exception as e:
            print(f"❌ Erro ao processar arquivo JSON:")
            traceback.print_exc()
            return False

    async def _save_log(self, log_entry: dict):
        try:
            # Atualizar o saldo antes de salvar o log
            if log_entry['steam_id'] != "Usuário não registrado" and log_entry['steam_id'] != "Erro ao buscar registro":
                print("\nIniciando atualização de saldo...")
                success, message, new_balance = await self.update_user_balance(
                    log_entry['steam_id'],
                    log_entry['valor_total']
                )
                balance_info = f"Novo saldo: {new_balance}" if success else f"Erro no saldo: {message}"
                print(f"Resultado da atualização: {balance_info}")
            else:
                balance_info = "Saldo não atualizado: Usuário não registrado"
                print(f"Saldo não atualizado: {log_entry['steam_id']}")

            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write('\n' + '='*50 + '\n')
                f.write(f"Data/Hora: {log_entry['timestamp']}\n")
                f.write(f"ID da Compra: {log_entry['purchase_id']}\n")
                f.write(f"ID do Usuário: {log_entry['user_id']}\n")
                f.write(f"Steam ID: {log_entry['steam_id']}\n")
                f.write(f"Valor Total: {log_entry['valor_total']}\n")
                if log_entry['codigos']:
                    f.write("Códigos:\n")
                    for codigo in log_entry['codigos']:
                        f.write(f"- {codigo}\n")
                f.write(f"Status do Saldo: {balance_info}\n")
                f.write('='*50 + '\n')
            print(f"Log salvo em: {os.path.abspath(self.log_file)}")
        except Exception as e:
            print(f"Erro ao salvar log: {e}")
            import traceback
            traceback.print_exc()

    async def update_user_balance(self, steam_id: str, valor: int) -> tuple[bool, str, int]:
        try:
            print(f"\nProcessando valor para Steam ID {steam_id}:")
            print(f"Valor a adicionar: {valor}")
            
            # Verificar se o caminho base está configurado
            if not self.bank_file_path:
                print("❌ BANK_FILE não está configurado ou acessível")
                return False, "Erro de configuração do caminho de arquivos", 0
            
            # Construir o caminho completo do arquivo do usuário
            if self.bank_file_path.startswith('\\\\'):
                # Para caminhos de rede, usar concatenação direta
                user_bank_file = f"{self.bank_file_path}{steam_id}.json"
            else:
                # Para caminhos locais, usar os.path.join
                user_bank_file = os.path.join(self.bank_file_path, f"{steam_id}.json")
                
            print(f"Tentando acessar arquivo: {user_bank_file}")
            
            # Obter lock para o arquivo
            file_lock = await get_file_lock(user_bank_file)
            
            async with file_lock:  # Usar lock para evitar concorrência
                try:
                    # Verificar se o arquivo existe
                    if not os.path.exists(user_bank_file):
                        print(f"❌ Arquivo de saldo não encontrado: {user_bank_file}")
                        return False, "Arquivo de saldo não encontrado", 0
                    
                    # Ler o arquivo atual
                    with open(user_bank_file, 'r', encoding='utf-8') as f:
                        user_data = json.load(f)
                    
                    # Obter a chave de saldo do .env ou usar "Balance" como padrão
                    balance_key = os.getenv('BALANCE_KEY', 'Balance')
                    
                    # Obter saldo atual (garantindo que seja inteiro)
                    try:
                        current_balance = int(user_data.get(balance_key, 0))
                        if current_balance < 0:
                            print("⚠️ Saldo atual é negativo, ajustando para 0")
                            current_balance = 0
                    except (ValueError, TypeError) as e:
                        print(f"❌ Erro ao converter saldo atual: {e}")
                        print(f"Valor problemático: {user_data.get(balance_key)}")
                        print("Resetando saldo para 0")
                        current_balance = 0
                    
                    print(f"Saldo atual lido: {current_balance}")
                    
                    # Validar valor a adicionar
                    if valor < 0:
                        print(f"❌ Valor negativo detectado: {valor}")
                        return False, "Valor negativo não permitido", current_balance
                    
                    # Calcular novo saldo
                    try:
                        new_balance = current_balance + valor
                        if new_balance < 0:  # Proteção extra contra overflow
                            print("⚠️ Novo saldo seria negativo, ajustando para 0")
                            new_balance = 0
                    except OverflowError as e:
                        print(f"❌ Erro de overflow ao calcular novo saldo: {e}")
                        return False, "Erro ao calcular novo saldo", current_balance
                    
                    print(f"Novo saldo calculado: {new_balance}")
                    
                    # Atualizar o arquivo
                    user_data[balance_key] = new_balance
                    
                    # Salvar as alterações
                    try:
                        with open(user_bank_file, 'w', encoding='utf-8') as f:
                            json.dump(user_data, f, indent=4)
                    except Exception as e:
                        print(f"❌ Erro ao salvar arquivo: {e}")
                        return False, "Erro ao salvar alterações", current_balance
                    
                    print(f"✅ Saldo atualizado com sucesso para Steam ID {steam_id}:")
                    print(f"   Saldo anterior: {current_balance}")
                    print(f"   Valor adicionado: {valor}")
                    print(f"   Novo saldo: {new_balance}")
                    return True, "Saldo atualizado com sucesso", new_balance
                    
                except json.JSONDecodeError as e:
                    print(f"❌ Erro ao ler arquivo JSON: {e}")
                    print(f"Conteúdo do arquivo problemático: {open(user_bank_file, 'r').read()}")
                    return False, "Erro ao ler arquivo de saldo", 0
                except PermissionError as e:
                    print(f"❌ Erro de permissão ao acessar arquivo: {e}")
                    return False, "Erro de permissão ao acessar arquivo de saldo", 0
                except Exception as e:
                    print(f"❌ Erro ao acessar arquivo: {e}")
                    traceback.print_exc()
                    return False, f"Erro ao acessar arquivo: {str(e)}", 0
                    
        except Exception as e:
            print(f"❌ Erro inesperado ao atualizar saldo: {e}")
            traceback.print_exc()
            return False, f"Erro ao atualizar saldo: {str(e)}", 0

@bot.event
async def on_message(message):
    try:
        # Verificar se a mensagem é do canal de confirmação de vendas
        sales_confirmation_channel_id = get_sales_confirmation_channel_id()
        if sales_confirmation_channel_id and message.channel.id == sales_confirmation_channel_id:
            print(f"Mensagem recebida no canal de confirmação de vendas: {message.id}")
            if message.attachments:
                print(f"Arquivos anexados encontrados")
                monitor = SalesConfirmationChannel(sales_confirmation_channel_id)
                for attachment in message.attachments:
                    print(f"Processando anexo: {attachment.filename}")
                    await monitor.process_json_file(attachment)
            else:
                print("Nenhum arquivo anexado encontrado na mensagem")
    except Exception as e:
        print(f"Erro no processamento da mensagem: {e}")
    
    await bot.process_commands(message)

async def check_role_permissions(guild: discord.Guild, bot_member: discord.Member, role: discord.Role) -> tuple[bool, str]:
    """Verifica as permissões do bot para gerenciar cargos"""
    try:
        # Debug: Imprimir informações detalhadas sobre os cargos
        print(f"\nVerificação de Permissões Detalhada:")
        print(f"Bot ID: {bot_member.id}")
        print(f"Bot Nome: {bot_member.name}")
        print(f"Bot Cargos: {[f'{r.name} (ID: {r.id}, Pos: {r.position})' for r in bot_member.roles]}")
        print(f"Bot Cargo Mais Alto: {bot_member.top_role.name} (Pos: {bot_member.top_role.position})")
        print(f"Bot é Admin: {bot_member.guild_permissions.administrator}")
        print(f"Bot pode gerenciar cargos: {bot_member.guild_permissions.manage_roles}")
        print(f"Cargo Alvo: {role.name} (ID: {role.id}, Pos: {role.position})")
        print(f"Cargo é gerenciado: {role.managed}")
        print(f"Cargo é integrável: {role.is_integration()}")
        print(f"Cargo é do bot: {role.tags.bot_id if role.tags and hasattr(role.tags, 'bot_id') else None}")
        print(f"Hierarquia de cargos válida: {bot_member.top_role.position > role.position}")
        
        # Se o bot é administrador, ele tem todas as permissões
        if bot_member.guild_permissions.administrator:
            print("[OK] Bot tem permissão de administrador")
            return True, "OK"
        
        # Verificações específicas
        if not bot_member.guild_permissions.manage_roles:
            print("[ERRO] Bot não tem permissão para gerenciar cargos")
            return False, "O bot não tem permissão para gerenciar cargos. Adicione a permissão 'Gerenciar Cargos' ao bot."
        
        if role.managed:
            print("[ERRO] Cargo é gerenciado por integração")
            return False, "Este cargo é gerenciado por uma integração e não pode ser modificado manualmente."
        
        if role.position >= bot_member.top_role.position:
            print("[ERRO] Cargo está acima ou na mesma posição do cargo mais alto do bot")
            return False, "O cargo do bot precisa estar acima do cargo que ele tentará gerenciar. Mova o cargo do bot para cima na hierarquia."
        
        if role.is_integration():
            print("[ERRO] Cargo é de integração")
            return False, "Este cargo é de integração e não pode ser modificado."
            
        print("[OK] Todas as verificações passaram")
        return True, "OK"
        
    except Exception as e:
        print(f"[ERRO] Erro na verificação de permissões: {e}")
        return False, f"Erro ao verificar permissões: {str(e)}"

async def remove_role_safely(member: discord.Member, role: discord.Role) -> tuple[bool, str]:
    """Remove um cargo de forma segura, tentando diferentes métodos"""
    try:
        # Verificar se o membro tem o cargo
        if role not in member.roles:
            return True, "Membro não possui o cargo"

        # Método 1: Remoção direta
        try:
            await member.remove_roles(role, reason="Remoção de verificação Steam")
            return True, "Cargo removido com sucesso (método direto)"
        except discord.Forbidden as e:
            print(f"Método 1 falhou: {e}")
            pass

        # Método 2: Edição completa de cargos
        try:
            new_roles = [r for r in member.roles if r != role]
            await member.edit(roles=new_roles, reason="Remoção de verificação Steam")
            return True, "Cargo removido com sucesso (método de edição completa)"
        except discord.Forbidden as e:
            print(f"Método 2 falhou: {e}")
            pass

        # Método 3: Remoção individual com delay
        try:
            await asyncio.sleep(1)  # Pequeno delay antes de tentar novamente
            await member.remove_roles(role, reason="Remoção de verificação Steam (com delay)")
            return True, "Cargo removido com sucesso (método com delay)"
        except discord.Forbidden as e:
            print(f"Método 3 falhou: {e}")
            return False, f"Não foi possível remover o cargo: {str(e)}"

    except Exception as e:
        print(f"Erro ao remover cargo: {e}")
        return False, f"Erro inesperado ao remover cargo: {str(e)}"

def is_file_processed(purchase_id: str) -> bool:
    """Verifica se um arquivo já foi processado"""
    # Limpar cache antigo (mais de 1 hora)
    current_time = time()
    processed_files.update({
        k: v for k, v in processed_files.items()
        if current_time - v < 3600  # 1 hora
    })
    
    return purchase_id in processed_files

def mark_file_processed(purchase_id: str):
    """Marca um arquivo como processado"""
    processed_files[purchase_id] = time()

bot.run(os.getenv('DISCORD_TOKEN')) 
