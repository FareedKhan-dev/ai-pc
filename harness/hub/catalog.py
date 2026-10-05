"""The services the hub can use, what to type when connecting each, and how to make the key (all free).

Each entry: label, fields [(name, prompt, secret)], steps (what the person does on the service's site), notes.
"""
SERVICES = {
    "slack": {
        "label": "Slack", "fields": [("bot_token", "Bot User OAuth Token (starts with xoxb-)", True)],
        "steps": ["Open https://api.slack.com/apps and click Create New App > From scratch; name it 'AI PC' and pick your workspace.",
                  "OAuth & Permissions > Bot Token Scopes: add chat:write, chat:write.public, channels:read, channels:history, groups:read, groups:history, "
                  "im:read, im:history, im:write, users:read, users:read.email, files:write, reactions:write.",
                  "Click Install to Workspace > Allow, then copy the Bot User OAuth Token (xoxb-...).",
                  "In Slack, invite the bot to each channel it should read or post in: /invite @AI PC"],
        "notes": "Free plan works (it shows the last 90 days of history)."},
    "telegram": {
        "label": "Telegram", "fields": [("bot_token", "Bot token from @BotFather", True)],
        "steps": ["In Telegram, open @BotFather and send /newbot; give it a name and a username ending in 'bot'.",
                  "Copy the token BotFather sends (1234567890:AA...).",
                  "Open your new bot and press Start (send it any message), so it can message you back."],
        "notes": "Free; good for alerts and briefings to your phone."},
    "trello": {
        "label": "Trello", "fields": [("key", "API key", True), ("token", "API token", True)],
        "steps": ["Open https://trello.com/power-ups/admin and click New; fill in a name (AI PC) and your workspace, then Create.",
                  "Open the app's API key tab and click Generate a new API key; copy the API key.",
                  "Next to the key, click the 'Token' link, press Allow, and copy the token."],
        "notes": "Free plan works."},
    "notion": {
        "label": "Notion", "fields": [("token", "Internal Integration Secret (ntn_... or secret_...)", True)],
        "steps": ["Open https://www.notion.so/profile/integrations and click New integration; type Internal, pick your workspace, Save.",
                  "Copy the Internal Integration Secret.",
                  "In Notion, open each page or database the AI PC may use: ... menu > Connections > add your integration."],
        "notes": "Free plan works; the integration sees only pages you share with it."},
    "google": {
        "label": "Google (Gmail, Calendar, Drive, Sheets)", "fields": [("client_id", "OAuth Client ID (....apps.googleusercontent.com)", False),
                                                                      ("client_secret", "OAuth Client secret", True)],
        "steps": ["Open https://console.cloud.google.com and create a project named 'AI PC'.",
                  "APIs & Services > Library: enable Gmail API, Google Calendar API, Google Drive API and Google Sheets API.",
                  "Google Auth Platform > Branding and Audience: External; add your own Gmail address as a Test user.",
                  "Google Auth Platform > Clients > Create client > Desktop app; copy the Client ID and Client secret.",
                  "Run hub.py connect google and paste them; a Google sign-in page opens once in your browser."],
        "notes": "Free. While the app is in 'Testing', Google asks you to sign in again every 7 days."},
    "microsoft": {
        "label": "Microsoft (Outlook mail and calendar, OneDrive; Teams with a work account)", "fields": [("client_id", "Application (client) ID", False)],
        "steps": ["Open https://entra.microsoft.com > App registrations > New registration; name 'AI PC'; Supported account types: "
                  "'Accounts in any organizational directory and personal Microsoft accounts'; Register.",
                  "Authentication > Advanced settings > Allow public client flows: Yes > Save.",
                  "API permissions > Add a permission > Microsoft Graph > Delegated: User.Read, Mail.ReadWrite, Mail.Send, Calendars.ReadWrite, Files.ReadWrite, "
                  "offline_access; for Teams (work or school accounts only) also Chat.ReadWrite, ChannelMessage.Send, Team.ReadBasic.All, Channel.ReadBasic.All.",
                  "Copy the Application (client) ID from Overview.",
                  "Run hub.py connect microsoft and paste it; then open https://microsoft.com/devicelogin and type the code shown."],
        "notes": "App registration needs a Microsoft Entra directory (every work or school account has one; a personal account can get one with a free Azure sign-up)."},
    "hubspot": {
        "label": "HubSpot CRM", "fields": [("token", "Private app access token (pat-...)", True)],
        "steps": ["In a free HubSpot account: Settings (gear) > Integrations > Private Apps (Legacy apps) > Create a private app.",
                  "Scopes: crm.objects.contacts.read and .write, crm.objects.companies.read and .write, crm.objects.deals.read and .write.",
                  "Create app, then copy the access token."],
        "notes": "Free CRM works."},
    "asana": {
        "label": "Asana", "fields": [("token", "Personal access token", True)],
        "steps": ["Open https://app.asana.com/0/my-apps and click Create new token; name it AI PC; copy the token."],
        "notes": "Free plan works."},
    "jira": {
        "label": "Jira", "fields": [("site", "Your site (e.g. yourteam.atlassian.net)", False), ("email", "Your Atlassian email", False), ("token", "API token", True)],
        "steps": ["Open https://id.atlassian.com/manage-profile/security/api-tokens and click Create API token; copy it.",
                  "Note your site address (yourteam.atlassian.net) and the email you sign in with."],
        "notes": "Free plan (up to 10 users) works."},
    "zoom": {
        "label": "Zoom", "fields": [("account_id", "Account ID", False), ("client_id", "Client ID", False), ("client_secret", "Client secret", True)],
        "steps": ["Open https://marketplace.zoom.us > Develop > Build App > Server-to-Server OAuth; name it AI PC.",
                  "Scopes: meeting:read:list_meetings:admin, meeting:write:meeting:admin, user:read:user:admin (or meeting:read:admin, meeting:write:admin, user:read:admin).",
                  "Activate the app, then copy the Account ID, Client ID and Client secret."],
        "notes": "Meetings work on the free plan; recordings and transcripts need a paid plan."},
    "whatsapp": {
        "label": "WhatsApp Business (Cloud API)", "fields": [("token", "Access token", True), ("phone_number_id", "Phone number ID", False)],
        "steps": ["Open https://developers.facebook.com > My Apps > Create App > type Business; add the WhatsApp product.",
                  "WhatsApp > API Setup: copy the temporary access token and the Phone number ID of the free test number.",
                  "Under 'To', add and verify your own phone number (up to 5 test recipients).",
                  "For a token that lasts: Business settings > System users > Generate token with whatsapp_business_messaging."],
        "notes": "The test number is free. Outside 24 hours of a customer's message, only approved templates can be sent (hello_world for testing)."},
    "figma": {
        "label": "Figma", "fields": [("token", "Personal access token (figd_...)", True)],
        "steps": ["Sign in at https://www.figma.com, open the account menu (your name, top left) > Settings > Security.",
                  "Under Personal access tokens click Generate new token; name it AI PC and pick an expiry (up to 90 days).",
                  "Scopes: current_user:read, file_content:read, file_metadata:read, file_comments:read and file_comments:write "
                  "(Read only for everything except Comments, which is Write).",
                  "Click Generate token and copy it (it starts with figd_ and is shown only once)."],
        "notes": "Free. Figma rations its API by seat: View and Collab seats can read a file up to 20 times a MONTH, Full and Dev seats about "
                 "10 times a minute. The AI PC keeps a copy of every file and asks Figma again only when the file has changed."},
    "canva": {
        "label": "Canva", "fields": [("client_id", "Client ID (OC-...)", False), ("client_secret", "Client secret", True)],
        "steps": ["In Canva turn on two-step sign-in first (Settings > Login & security > Multi-factor authentication); Canva requires it.",
                  "Open https://www.canva.com/developers/integrations, click Create an integration, choose Public and name it AI PC "
                  "(it stays a draft that only your own account can use; do not submit it for review).",
                  "Configuration > Credentials: copy the Client ID; click Generate secret and copy the Client secret (shown once).",
                  "Scopes: profile:read, design:meta:read, design:content:read, design:content:write, asset:read, asset:write, folder:read.",
                  "Redirect URLs: add http://127.0.0.1:3001/oauth/redirect",
                  "Run hub.py connect canva and paste them; a Canva sign-in page opens once in your browser (click Allow)."],
        "notes": "Free plan works: a draft integration needs no review and serves only your account (Private integrations need Canva "
                 "Enterprise). Some exports, like transparent PNGs, need Canva Pro."},
}
ORDER = ["slack", "telegram", "trello", "notion", "google", "microsoft", "hubspot", "asana", "jira", "zoom", "whatsapp", "figma", "canva"]
