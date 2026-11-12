# Security

## Reporting a problem

Please report security problems privately, through **Report a vulnerability** on the repository's
[Security tab](https://github.com/kanggu12/openDMT3/security), not in an issue. Say what an attacker can do, on which
part (the launcher, a server with Docker, a server with Python), and how to reproduce it. You will get an answer
within a week, and credit in the release notes if you want it.

## What counts

- A way past a sign-in: the site's, the admin pages', the API's tokens, or the launcher's sign-in to a server.
- Reading or changing another player's data, or a server's files, from the network.
- A backup upload that the server keeps or opens without its checks, or that writes outside its backups folder.
- An archive or a song list that, unpacked or taken in, writes outside the folder it goes to, or a song list upload
  the server takes without its checks.
- An update the launcher puts in without the project's signature beside it.
- The launcher writing into the client data (only **Put back** and removing openDMT3 do, and only inside it), or
  outside its own folders and what the player asked for: **Unpack** and a song list saved where the player chose, and
  on the Desktop a report and the shortcut that plays at once.
- Secrets (passwords, card numbers, tokens) in logs, pages or error messages.

The game logs a player in with a card number alone, as a real card does, so a login with someone else's card number
is known and not a vulnerability of openDMT3: card numbers are shown only to their owner, and a new password makes a
new one. [docs/architecture.md](../docs/architecture.md#security) says what the server does against floods and forged
results.

## Supported versions

Fixes go into `main` and the next release. The launcher stays safe on the latest one: **Launcher**, **Check for
updates** (or `openDMT3-cmd.exe --update`). A server with Docker: `git pull`, then `./dmt3 up`; with Python:
`git pull`, then start it again.
