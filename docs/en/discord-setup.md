# Setting up Discord

*[Deutsche Fassung](../de/discord-setup.md)* · Back to the
[overview](../../README.md).

The Discord plugin controls the **running Discord client** through its local
RPC interface — exactly what you expect from a Stream Deck: mute your own
microphone, deafen yourself, switch voice or text channels.

What does **not** work: turning the camera and "Go Live" on and off.
Discord's RPC interface simply has no commands for that — this is a gap in
the interface, not in this plugin.

Discord requires an application of your own in the developer portal. That is
a few minutes of one-time clicking. Since you own that application yourself,
you may authorise it for RPC access without approval from Discord.

## 1. Create the application

1. Open <https://discord.com/developers/applications>
2. **New Application** → pick a name (e.g. "Stream Deck") → **Create**
3. Under **OAuth2**, add the redirect URI `http://localhost` and save

## 2. Copy the credentials

On the **OAuth2** page:

* **Client ID** → this is the *application ID*
* **Client Secret** → click **Reset Secret** once and copy the value

The secret is needed exactly once: to exchange the authorisation code for a
long-lived access token.

## 3. Enter them in the interface

*Plugins → Discord → Plugin settings*

| Field | Value |
| --- | --- |
| Application ID | the client ID |
| Client secret | the client secret |
| Redirect URI | `http://localhost` (identical to the developer portal) |

Click **Save**, then **Connect to Discord**.

## 4. Confirm access

The running Discord client shows a dialogue asking permission for the
application. Once confirmed the connection is done — the access token lands
in `~/.config/deckswitch/discord-token.json` (mode 0600) and is used
automatically from then on.

The token deliberately does **not** live in `config.json`: that file can be
exported and passed on, and the token should not travel with it.

## Troubleshooting

**"No Discord IPC socket found"**
The Discord client is not running. For Flatpak or Snap installations the
plugin also looks in the respective runtime directories; if it finds nothing
there, a native installation helps.

**"Authorisation failed"**
Usually the redirect URI in the developer portal does not match the one in
the plugin settings exactly, or the secret has since been reset. Use **Clear
authorisation** to discard the stored token and connect again.

**Keys show "not connected" (dimmed)**
That is the regular state while Discord is not running — the plugin retries
every few seconds and redraws the keys as soon as it succeeds.
