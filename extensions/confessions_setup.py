"""
  Confessions Setup - Easy setup experience for anonymous messaging
  Note: Contains generic command names like setup, list, and block
    As a result, this only really suits a singlular purpose bot
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
import disnake
from disnake.ext import commands

if TYPE_CHECKING:
  from main import MerelyBot
  from babel import Resolvable
  from configparser import SectionProxy

from extensions.controlpanel import Toggleable, Stringable
from overlay.extensions.confessions_common import \
  ChannelType, ChannelSelectView, get_channeltypes, findvettingchannel, get_guildchannels,\
  set_guildchannels


class ConfessionsSetup(commands.Cog):
  """ Configure anonymous messaging on your server """
  SCOPE = 'confessions'

  @property
  def config(self) -> SectionProxy:
    """ Shorthand for self.bot.config[scope] """
    return self.bot.config[self.SCOPE]

  def babel(self, target:Resolvable, key:str, **values: dict[str, str | bool]) -> str:
    """ Shorthand for self.bot.babel(scope, key, **values) """
    return self.bot.babel(target, self.SCOPE, key, **values)

  def __init__(self, bot:MerelyBot):
    self.bot = bot

    # ensure config file has required data
    if not bot.config.has_section(self.SCOPE):
      bot.config.add_section(self.SCOPE)
    if 'pfpgen_url' not in self.config or self.config['pfpgen_url'] == '':
      self.config['pfpgen_url'] = ''
      if not bot.quiet:
        print(
          " - WARN: You don't have a pfp generator. Profile pictures in webhook mode will be blank."
        )
    if 'confessions' not in bot.config['extensions']:
      if not bot.quiet:
        print(" - WARN: Without Confessions enabled, users won't be able to confess!")

  def controlpanel_settings(self, inter:disnake.Interaction):
    # ControlPanel integration
    out = [Toggleable(self.SCOPE, f'{inter.user.id}_dm_notif', 'dm_notifications', default=True)]
    if inter.guild is None:
      return out
    if inter.permissions.administrator:
      out += [
        Toggleable(self.SCOPE, f'{inter.guild_id}_imagesupport', 'image_support', default=True),
        Toggleable(self.SCOPE, f'{inter.guild_id}_webhook', 'enable_webhooks', default=False),
        Stringable(self.SCOPE, f'{inter.guild_id}_preface', 'confession_preface')
        #TODO: Add custom pfp stringable, Anon-ID usernames, Anon-Colour pfps
      ]
    return out

  def controlpanel_theme(self) -> tuple[str, disnake.ButtonStyle]:
    # Controlpanel custom theme for buttons
    return (self.SCOPE, disnake.ButtonStyle.blurple)

  class SetupView(ChannelSelectView):
    """ Configure channels and shortcuts to configure guild settings """
    current_channel: disnake.TextChannel
    current_mode: ChannelType

    def __init__(
      self,
      inter:disnake.GuildCommandInteraction,
      parent:ConfessionsSetup,
      channel:disnake.TextChannel
    ):
      """
        A SetupView extends upon ChannelSelectView

        Adds a mode select, an untraceable toggle, and documentation about channel types.
      """
      # Find channel types in config
      matches = self.regenerate_matches(parent, inter.guild)
      super().__init__(inter, parent, matches)
      self.channel_selector.callback = self.channel_selector_override
      self.channel_selector.placeholder = self.parent.babel(inter, 'setup_placeholder')
      self.mode_selector.options = [
        disnake.SelectOption(
          label=mode.localname(babel=parent.bot.babel, target=inter, long=False),
          value=mode.value,
          emoji=mode.icon
        )
        for mode in get_channeltypes(self.parent.bot.cogs) if mode.value not in (0, 4)
      ]
      self.remove_item(self.send_button)
      self.help.label = parent.babel(inter, 'setup_help')
      self.toggle_anon_ids.label = parent.babel(inter, 'setup_anonids')
      if 'ControlPanel' in parent.bot.cogs:
        linkbutton = disnake.ui.Button(
          custom_id='controlpanel',
          label=parent.babel(inter, 'setup_controlpanel'),
          style=disnake.ButtonStyle.grey,
          emoji='💡',
          row=4
        )
        linkbutton.callback = self.controlpanel_shortcut
        self.add_item(linkbutton)

      self.current_channel = channel
      guildchannels = get_guildchannels(parent.config, inter.guild.id)
      self.current_mode = guildchannels.get(channel.id, ChannelType.unset())
      self.update_state()

    def regenerate_matches(
      self, parent:ConfessionsSetup, guild:disnake.Guild
    ) -> tuple[disnake.TextChannel, ChannelType]:
      """ Create a list of all channels on the server sorted by categories and position """
      if len(guild.channels) == 0:
        return []
      botmember = guild.get_member(parent.bot.user.id)
      guildchannels = get_guildchannels(parent.config, guild.id)
      out = [(c, guildchannels.get(c.id, ChannelType.unset())) for c in guild.channels if (
        isinstance(c, disnake.TextChannel) and c.permissions_for(botmember).read_messages
      )]
      out.sort(key=lambda t: (t[0].category.position if t[0].category else 0, t[0].position))
      return out

    async def controlpanel_shortcut(self, inter:disnake.MessageInteraction):
      """
        Invite the user to change server-wide settings in the controlpanel

        This is here because some users may expect server-wide settings to be in a command called
          /setup
      """
      if 'ControlPanel' not in self.parent.bot.cogs:
        raise Exception("ControlPanel was unloaded")
      await self.parent.bot.cogs['ControlPanel'].controlpanel(inter)

    async def set(
      self, inter:disnake.MessageInteraction, channel:disnake.TextChannel, mode:ChannelType
    ) -> bool:
      """ Tries to change settings as requested and handles all rules and requirements """
      guildchannels = get_guildchannels(self.parent.config, channel.guild.id)
      wastype = int(guildchannels.get(channel.id, ChannelType.unset()))
      if mode == ChannelType.unset():
        if wastype == ChannelType.unset():
          await inter.send(self.parent.babel(inter, 'unsetfailure'), ephemeral=True)
          return False
        guildchannels.pop(channel.id)
      elif mode == ChannelType.vetting():
        if 'ConfessionsModeration' not in self.parent.bot.cogs:
          await inter.send(self.parent.babel(inter, 'no_moderation'), ephemeral=True)
          return False
        if findvettingchannel(guildchannels):
          await inter.send(self.parent.babel(inter, 'singlechannel'), ephemeral=True)
          return False
      if wastype == mode:
        await inter.send(self.parent.babel(inter, 'no_change'), ephemeral=True)
        return False
      if mode != ChannelType.unset():
        guildchannels[channel.id] = mode
      set_guildchannels(self.parent.config, channel.guild.id, guildchannels)
      self.parent.bot.config.save()

      #BABEL: setsuccess#,unsetsuccess#
      modestring = (
        f'setsuccess{mode.value}' if mode != ChannelType.unset() else f'unsetsuccess{wastype}'
      )
      #BABEL: setundo,unsetundo
      try:
        await channel.send(
          self.parent.babel(inter.guild, modestring) + ' ' +
          self.parent.babel(inter.guild, 'setundo' if mode != ChannelType.unset() else 'unsetundo') +
          ('\n'+self.parent.babel(inter.guild, 'setcta') if mode != ChannelType.unset() else '')
        )
      except disnake.Forbidden:
        pass
      # Update appearance of SetupView to reflect changes
      self.current_mode = mode
      self.matches = self.regenerate_matches(self.parent, inter.guild)
      self.update_list()
      self.update_state()
      await self.update_message(inter)
      return True

    def update_state(self):
      """ Update state of all buttons and selects to match config """
      # Toggle AnonIDs button state
      self.toggle_anon_ids.disabled = self.current_mode.value not in ChannelType.SWAPS
      self.toggle_anon_ids.emoji = '🟢' if self.current_mode.anonid else '⭕'
      # modeval is only for the dropdown, the true value is still stored in current_mode
      modeval = self.current_mode.value
      if self.current_mode.value in ChannelType.SWAPS and not self.current_mode.anonid:
        modeval = ChannelType.SWAPS[modeval]
      # Channel selector state
      for option in self.channel_selector.options:
        option.default = bool(int(option.value) == self.current_channel.id)
      # Mode selector state
      for option in self.mode_selector.options:
        option.default = (
          int(option.value) == modeval
        )

    async def update_message(self, inter:disnake.MessageInteraction):
      modename = self.current_mode.localname(self.parent.bot.babel, inter)
      self.timeout = 180
      self.help.disabled = True
      #BABEL: state_desc_#
      descmode = 'state_desc_' + str(self.current_mode.value)
      await inter.response.edit_message((
        self.parent.babel(inter, 'setup_state', channel=self.current_channel.mention, state=modename)
        + '\n' + self.parent.babel(inter, descmode)
        + '\n' + self.parent.babel(inter, 'state_cta')
      ), view=self)

    async def channel_selector_override(self, inter:disnake.MessageInteraction):
      """ Update the message to preview the selected target """
      if inter.user != self.origin.author:
        await inter.send(self.parent.bot.babel(inter, 'error', 'wronguser'))
        return
      self.send_button.disabled = False
      try:
        self.current_channel = await self.parent.bot.fetch_channel(int(inter.values[0]))
      except disnake.Forbidden:
        self.current_mode = ChannelType.unset()
        self.update_state()
        await self.update_message(inter)
        await inter.send(
          content=self.parent.babel(inter, 'setup_state_missing', channel_id=inter.values[0]),
          ephemeral=True
        )
        return
      c = self.current_channel
      guildchannels = get_guildchannels(self.parent.config, c.guild.id)
      self.current_mode = guildchannels.get(c.id, ChannelType.unset())
      self.update_state()
      await self.update_message(inter)

    @disnake.ui.button(emoji='❓', row=4)
    async def help(self, _:disnake.ui.Button, inter:disnake.MessageInteraction):
      self.update_state()
      await self.update_message(inter)

    @disnake.ui.button(emoji='🟢', row=4)
    async def toggle_anon_ids(self, _:disnake.ui.Button, inter:disnake.MessageInteraction):
      if self.current_mode.value in ChannelType.SWAPS.keys():
        self.current_mode = ChannelType(ChannelType.SWAPS[self.current_mode.value])
        await self.set(inter, self.current_channel, self.current_mode)

    @disnake.ui.select()
    async def mode_selector(self, _:disnake.ui.Select, inter:disnake.MessageInteraction):
      if inter.user != self.origin.author:
        await inter.send(self.parent.bot.babel(inter, 'error', 'wronguser'))
        return

      await self.set(inter, self.current_channel, ChannelType(int(inter.values[0])))

    async def on_timeout(self):
      for component in self.children:
        if isinstance(component, (disnake.ui.Button, disnake.ui.Select)):
          component.disabled = True
      try:
        msg = await self.origin.original_message()
        await msg.edit(view=self)
      except disnake.HTTPException:
        pass

  # Events

  @commands.Cog.listener('on_ready')
  async def config_verify(self):
    """ Ensure guilds stored in config are still accessible to the bot """
    await asyncio.sleep(15)

    if self.bot.verbose:
      print("Starting lost guild search")
    removed = []
    for key in self.config:
      guild_id = key.split('_')[0]
      if guild_id.isdigit():
        guild = self.bot.get_guild(int(guild_id))
        # Remove config for any guilds the bot can't access
        if guild is None:
          self.config.pop(key)
          if not self.bot.quiet and guild_id not in removed:
            print("Removed guild", guild_id, "from config.")
          removed.append(guild_id)
        # Remove config for any channels the bot can't access
        elif key.endswith('_channels'):
          guildchannels = get_guildchannels(self.config, guild.id)
          for channel_id in list(guildchannels):
            if guild.get_channel(channel_id) is None:
              guildchannels.pop(channel_id)
              if not self.bot.quiet:
                print("Removed channel", channel_id, "from guild", guild_id, "config.")
          set_guildchannels(self.config, guild.id, guildchannels)

    self.bot.config.save()
    if self.bot.verbose:
      print("Completed lost guild search")

  @commands.Cog.listener('on_guild_remove')
  async def guild_cleanup(self, guild:disnake.Guild):
    """ Automatically remove data related to a guild on removal """
    removed = False
    for key in list(k for k in self.config if k.startswith(str(guild.id)+'_')):
      self.config.pop(key)
      removed = True
    self.bot.config.save()
    if removed and not self.bot.quiet:
      print("Removed guild", guild.id, "from config.")

  @commands.Cog.listener('on_guild_channel_delete')
  async def channel_cleanup(self, channel:disnake.TextChannel):
    """ Automatically remove data related to a channel on delete """
    guildchannels = get_guildchannels(self.config, channel.guild.id)
    if channel.id in guildchannels:
      guildchannels.pop(channel.id)
      if not self.bot.quiet:
        print("Removed channel", channel.id, "from guild", channel.guild.id, "config.")
      set_guildchannels(self.config, channel.guild.id, guildchannels)
    self.bot.config.save()

  # Commands

  @commands.default_member_permissions(manage_channels=True)
  @commands.slash_command(dm_permission=False)
  async def setup(self, inter:disnake.GuildCommandInteraction):
    """
      Change confessions settings on this server
    """
    channel = self.bot.get_channel(inter.channel_id)
    await inter.response.send_message(
      self.babel(inter, 'setup_start'), view=self.SetupView(inter, self, channel), ephemeral=True
    )

  @commands.default_member_permissions(moderate_members=True)
  @commands.slash_command(dm_permission=False)
  async def shuffle(self, inter:disnake.GuildCommandInteraction):
    """
      Change all anon-ids on a server
    """
    if str(inter.guild.id)+'_banned' in self.config:
      await inter.send(self.babel(inter, 'shufflebanresetwarning'))

      def check(m:disnake.Message):
        return m.channel == inter.channel and\
               m.author == inter.author and\
               m.content.lower() == 'yes'
      try:
        await self.bot.wait_for('message', check=check, timeout=30)
      except asyncio.TimeoutError:
        await inter.send(self.babel(inter, 'timeouterror'))
      else:
        self.config.pop(str(inter.guild.id)+'_banned')

    shuffle = int(self.config.get(f'{inter.guild.id}_shuffle', fallback=0))
    self.bot.config.set(self.SCOPE, str(inter.guild.id)+'_shuffle', str(shuffle + 1))
    self.bot.config.save()

    await inter.send(self.babel(inter, 'shufflesuccess'))

  @commands.default_member_permissions(administrator=True)
  @commands.slash_command(dm_permission=False)
  async def imagesupport(self, inter:disnake.GuildCommandInteraction):
    """
      Enable or disable images in confessions
    """
    #TODO: delete this in time as users adjust
    if 'Help' in self.bot.cogs:
      await self.bot.cogs['Help'].help(inter, 'imagesupport', ephemeral=True)

  @commands.default_member_permissions(administrator=True)
  @commands.slash_command(dm_permission=False)
  async def botmod(self, inter:disnake.GuildCommandInteraction):
    """
      Grant or take away botmod powers from a user
    """
    #TODO: delete this in time as users adjust
    await inter.response.send_message(self.babel(inter, 'botmod_removed'))


def setup(bot:MerelyBot) -> None:
  """ Bind this cog to the bot """
  bot.add_cog(ConfessionsSetup(bot))
