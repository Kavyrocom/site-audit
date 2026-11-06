# Internal audit (back end, read-only)

From outside you see what a visitor sees. With access to the back end you can see **why**: the PHP version, the plugins that are out of date, the 500 errors in the logs, the 12 MB of options loaded on every page, the forgotten backup file. That is a deeper audit. It is also riskier, so it follows stricter rules.

## 1. Ask, then verify, then ask again

In step 0, ask: **"Outside view only, or outside + inside? Inside needs read access to the back end."** If inside:

1. Ask which accesses the person can give, from this list: `ssh` (best), `wp` (WordPress admin through an application password), `ftp` (FTP over TLS; SFTP goes through the `ssh` type), `files` (the site folder is on this machine), hosting or CDN panel, Search Console, analytics, tag manager.
2. For each one given, **verify it before you rely on it**: `python3 -I <S>/access_check.py ssh|wp|ftp|files ...`. It only reads, and prints what the access allows (role, write rights, WP-CLI present...).
3. **Collect everything missing in one message** and say exactly what to provide (`next_step` of the script). Never ask twice for the same thing.
4. **Do not wait to start.** Run the whole outside audit now. The inside part starts when an access is verified. If it never comes, deliver the outside audit and put the inside part in `not_measured`.

A secret is never pasted in the chat and never typed on a command line. The person puts it in the environment (or the agent's secret store) and tells you the **name** of the variable. If a secret appears in the chat anyway, do not repeat it, do not store it, and tell the person to change it.

Fill `meta.audit_depth` with `external_internal` and `meta.internal_access` with the list of accesses `access_check.py` confirmed (for example `["ssh", "wp"]`). Mark each inside finding with `"layer": "internal"`. `build_report.py` refuses an inside finding without a verified access.

## 2. Rules for the inside

- **Read-only, always.** No write, no install, no update, no cache purge, no restart, no cron, no `wp ... update`, no SQL other than `SELECT`. Fixes belong to phase 2, with a GO.
- **Fixed, boring commands.** Use the list below. Do not run a command a person did not expect. Never run anything heavy on a production database without saying so (a `SELECT` over a big table, a full-disk `find`): use `LIMIT`, `-maxdepth`, `ionice`/`nice`.
- **Never read a secrets file to look at it.** Do not `cat` `wp-config.php`, `.env`, private keys or credentials files. To know a setting exists, ask for its **name** (`wp config list --fields=name`, `grep -c DB_PASSWORD`). Whatever you save goes through `<command> | python3 -I <S>/redact.py --out internal/<name>.txt` first. Evidence files contain commands and outputs, never secrets.
- **Personal data.** Logs and databases hold visitor IPs and emails. Aggregate (counts, top URLs), never copy lines with personal data into the report. `redact.py` masks e-mail addresses, IP addresses and phone numbers as a safety net, and `build_report.py` refuses an inside-view report that still contains one; names in free text or in a table (`wp user list`) are NOT masked, so ask for counts and roles (`wp user list --format=count`, `--fields=roles`).
- **Say what you could not read.** Wrong rights, no WP-CLI, no log access: it goes in `not_measured`.
- Evidence format: `command` + the relevant lines, saved in `internal/`, and named in the finding (`evidence: internal/wp-plugins.txt: 9 of 24 plugins have an update, 2 more than 1 year old`).

## 3. What to look at, by access

### ssh (or files on this machine)
| Look at | Read-only command | Why it matters |
|---|---|---|
| Server and PHP | `php -v`, `nginx -v` or `apache2 -v`, `uname -sr`, `cat /etc/os-release` | PHP out of support = security and speed |
| Pending system updates | `apt list --upgradable 2>/dev/null` (or `dnf check-update`) | security patches |
| Disk, memory, load | `df -h`, `free -m`, `uptime` | a full disk takes a site down |
| Error logs, last 7 days | count and top messages from the web server and PHP logs | fatal errors, 5xx, timeouts that visitors meet |
| Access logs | top 404 URLs, top 5xx URLs, slow URLs if the log has request time, share of bots (Googlebot, AI crawlers) | real broken links, crawl waste |
| Exposed files | look for `.git`, `.env`, `*.sql`, `*.zip`, `*.bak`, `phpinfo.php`, `wp-config.php.bak` under the web root: `find <webroot> -maxdepth 3 \( -name ".git" -o -name ".env" -o -name "*.sql" -o -name "*.bak" -o -name "*.zip" \)` | forgotten files that leak data |
| Permissions | `find <webroot> -maxdepth 3 -perm -o+w -not -type l` | world-writable files and folders |
| Web server config | gzip or brotli, cache headers for static files, HTTP/2, TLS versions, redirects, security headers, directory listing | speed, security |
| TLS certificate | `openssl x509 -noout -dates -in <cert>` or via `openssl s_client` | expiry |
| Backups | newest backup file date and size in the known backup folder, or the host's backup job | can you recover? |
| Scheduled jobs | `crontab -l`, systemd timers | forgotten or missing jobs |
| Static or custom sites | source maps in production, unminified assets, hard-coded `http://` URLs, large unoptimised images in `uploads` | speed, mixed content |

### WordPress (WP-CLI over ssh, or REST with an application password)
| Look at | Command | Why |
|---|---|---|
| Core, plugins, themes versions | `wp core version`, `wp core check-update`, `wp plugin list --fields=name,status,version,update`, `wp theme list --fields=name,status,version,update` | outdated code is the first way in |
| Abandoned plugins | for each active plugin, last update date on wordpress.org (public) | no support |
| Inactive but installed plugins and themes | same list, `status=inactive` | attack surface |
| Debug mode on production | `wp config get WP_DEBUG` (value of this one only) | leaks paths and notices |
| Search engines blocked | `wp option get blog_public` (0 = discouraged) | an invisible site |
| Permalinks, homepage setting | `wp option get permalink_structure`, `wp option get show_on_front` | SEO basics |
| Autoloaded options weight | `wp db query "SELECT ROUND(SUM(LENGTH(option_value))/1024) AS kb FROM wp_options WHERE autoload IN ('yes','on','auto','auto-on')"` (adjust prefix; WordPress 6.6 and later also use the values on, auto and auto-on) | over about 1 MB slows every page |
| Revisions, transients, orphan data | counts only, with `SELECT COUNT(*)` | bloat |
| Cron | `wp cron event list --fields=hook,next_run_relative` | stuck or missing jobs |
| Cache and object cache | which cache plugin, `wp cache type`, drop-ins in `wp-content` | speed |
| Admin users | `wp user list --role=administrator --format=count` (a count only: names and logins are personal data, `redact.py` cannot mask a name in free text) | too many admins |
| Consent and tracking tools | active plugins that load tags (two consent tools is a finding) | compliance, speed |
| Image sizes and media weight | size of `wp-content/uploads`, number of files over 1 MB | page weight |
| Forms | which form plugin, where the submissions go (settings screen) | leads lost silently |

With **REST only** (application password, no ssh), you can read: the plugin list (`/wp-json/wp/v2/plugins`, needs an admin role), the theme (`/wp-json/wp/v2/themes`), site settings (`/wp-json/wp/v2/settings`), pages, drafts, redirects if a plugin exposes them. `access_check.py wp` says what the role allows.

### ftp (FTP over TLS) and sftp
You can read files, not run commands. (SFTP is opened with `access_check.py ssh`; the ssh key gives a shell unless the account is restricted, say what the check found.) Look at `robots.txt`, `.htaccess`, theme and plugin folders (version lines in `readme.txt` or the file headers), the uploads folder weight, forgotten backups and `*.sql`. Everything about logs, versions of the server and the database stays `not_measured`.

### Admin panels (CMS, hosting, CDN, tag manager, Search Console, analytics)
Read the settings screens a developer would read: cache and compression rules, redirect rules, WAF, DNS records (SPF, DKIM, DMARC for e-mail deliverability), tag manager containers (what fires, on which trigger), Search Console coverage and queries, analytics goals and conversions. If the person can export a report, ask for the export instead of access.

## 4. Turning it into findings

- Same finding format as the outside audit, with `"layer": "internal"` and an `evidence` that names the file in `internal/`.
- A fix found inside usually has `execution.mode: agent` when the access that found it also allows the change (`access_check.py` says: write rights, WP-CLI) and `risk` honest: updating a plugin is `medium` (visible if it breaks, reversible with a backup), editing `.htaccess` redirects is `high`.
- Combine with the outside view: the 500 error in the log and the slow page in Lighthouse are one finding, not two.
- Strengths count: a recent backup, supported PHP, clean permissions are things that work.
