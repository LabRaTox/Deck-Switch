# Setting up Discord

*[Deutsche Fassung](../de/discord-setup.md)* · Back to the
[overview](../../README.md) or to
[Setting up store plugins](store-plugin-setup.md).

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

The plugin needs the secret twice. Once to exchange the authorisation code
for an access token, and again every time it renews that token. So leave it
in the settings.

## 3. Enter them in the GUI

*Plugins → Discord → Plugin settings*

| Field | Value |
| --- | --- |
| Application ID | the client ID |
| Client secret | the client secret |
| Redirect URI | `http://localhost` (identical to the developer portal) |
| Connect automatically | on (default): the plugin connects when the backend starts and retries while Discord is not running. Off: only through the button |

Click **Save**, then **Connect to Discord**.

## 4. Confirm access

The running Discord client shows a dialog asking permission for the
application. Once you confirm, the connection is done. The access token lands
in `~/.config/deckswitch/discord-token.json` with mode 0600 and is used
automatically from then on.

Discord issues the token for 7 days. One day before it expires, the plugin
fetches a new one by itself, without showing the dialog again. That renewal
needs the client secret. If the field is empty, the plugin skips it, and after
7 days you have to connect again.

The token deliberately does not live in `config.json`. That file can be
exported and passed on, and the token should not travel with it.

## Troubleshooting

**"No Discord IPC socket found"**
The Discord client is not running. For Flatpak or Snap installations the
plugin also looks in the respective runtime folders. If it finds nothing
there, a native installation helps.

**"Sign-in failed: …"**
Behind the colon Discord's reason follows.

* "The client secret does not match the application ID." The secret was
  copied wrongly or has been reset in the developer portal since. Copy the
  current one.
* "The authorization code was rejected. Usually the redirect URI differs
  from the one in the Developer Portal." Both have to match exactly.
* "The requested RPC permissions were denied." Discord did not grant the
  permissions the plugin asks for.

After fixing it, throw the stored token away with **Remove authorisation**
and connect again.

**"Discord refused to renew the sign-in. Please connect again in the plugin
settings."**
This one is in the backend log. Discord did not accept the stored token for
renewal, or the secret has been reset since. Enter the current secret, save
and press **Connect to Discord**.

**Keys show "not connected" (dimmed)**
That is the normal state while Discord is not running. With *Connect
automatically* switched on, the plugin retries every few seconds and redraws
the keys as soon as it works.
