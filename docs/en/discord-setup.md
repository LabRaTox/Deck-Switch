# Setting up Discord

*[Deutsche Fassung](../de/discord-setup.md)* · Back to the
[overview](../../README.md).

The Discord plugin controls the **running Discord client** through its local
RPC interface. So exactly what you would expect from a Stream Deck: mute your
own microphone, deafen yourself, switch voice or text channel.

What does **not** work: turning the camera and "Go Live" on and off. Discord's
RPC interface has no commands for those. That is not a gap in this plugin but
one in the interface.

Discord requires an application of your own in the developer portal. It is a
few minutes of clicking, once. Since you own that application yourself, you
may authorise it for RPC access without Discord approving anything.

## 1. Create the application

1. Open <https://discord.com/developers/applications>
2. **New application** → give it a name (for example "Stream Deck") →
   **create**
3. Under **OAuth2**, add the redirect URI `http://localhost` and save

## 2. Copy the credentials

On the **OAuth2** page:

* **Client ID** is the *application ID*
* **Client secret** you get through **reset secret**, then copy the value

You only need the secret once, namely to exchange the authorisation code for
a lasting access token.

## 3. Enter them in the GUI

*Plugins → Discord → plugin settings*

| Field | Value |
| --- | --- |
| Application ID | the client ID |
| Client secret | the client secret |
| Redirect URI | `http://localhost` (identical to the developer portal) |

Click **save**, then **connect to Discord**.

## 4. Confirm access

The running Discord client shows a dialog asking permission for the
application. Once you confirm, the connection is done. The access token lands
in `~/.config/deckswitch/discord-token.json` with mode 0600 and is used
automatically from then on.

The token deliberately does not live in `config.json`. That file can be
exported and passed on, and the token should not travel with it.

## Troubleshooting

**"No Discord IPC socket found"**
The Discord client is not running. For Flatpak or Snap installations the
plugin also looks in the respective runtime folders. If it finds nothing
there, a native installation helps.

**"Sign-in failed"**
Usually the redirect URI in the developer portal does not exactly match the
one in the plugin settings, or the secret has been reset since. Throw the
stored token away with **clear authorisation** and connect again.

**Keys show "not connected" (dimmed)**
That is the normal state while Discord is not running. The plugin retries
every few seconds and redraws the keys as soon as it works.
