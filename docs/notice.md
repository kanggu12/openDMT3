# License and notice

For everyone who plays with openDMT3, runs an openDMT3 server, or works on the code. It is not legal advice. The
launcher's **Launcher** page and the site's footers say what the project is and that the project acts on rights
holders' requests.

## The project

openDMT3 is an unofficial, non-commercial community project. It is not affiliated with or endorsed by NEOWIZ. DJMAX
and TECHNIKA are trademarks of NEOWIZ, and the game is NEOWIZ's copyrighted work.

openDMT3 is a launcher and a server. The repository and its releases contain none of the game's files: no game client,
songs, charts, images, videos or sounds. The launcher works only with client data its owner provides, with a client
that runs on a PC, and only reads it: what it needs to play it is made in a folder of openDMT3's own. A server reads
only the song list, which holds the jackets and the DJ cards too (no charts, music or videos), from its owner's own
client data, in a folder or in an archive, or from a song list openDMT3's own code made from that client data (the
launcher's **Save the song list...**); without it its pages show song numbers and no jackets
([The client data](client-data.md)).

What the repository does hold is openDMT3's own code and what it takes to work with those files: the names of the game's
files it reads, the shapes of the messages the game sends and of the replies it reads ([docs/protocol.md](protocol.md)),
the client builds it recognizes by their hashes, the short byte patterns PLAY changes in its copy of the PC client,
and a card reader library of its own that takes the cabinet's place (`native/cardreader`).

## For rights holders

This project respects the rights of NEOWIZ and other rights holders.
This repository contains no game data. If the copyright holder requests it, this project may be made private or shut
down, in whole or in the part concerned, and promptly. No lawsuit or formal notice is needed: a request in the
repository's issues is enough, saying who is asking and what it concerns. The maintainer can act on this repository's
own contents; about a fork, another copy or a particular server, please contact whoever runs it.

## License

openDMT3's own code and documentation are under the MIT License: see [LICENSE](../LICENSE).

The license does not cover the game or its files. Those are not in the repository and are not licensed by it.

Nor does it cover third-party parts, which keep their own licenses. [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
lists each with where it goes (the fonts, what the launcher puts beside the game, the launcher, 7-Zip, the server's
packages and its container image) and where its full text travels with it.

## If you play

- openDMT3 works with client data you provide; it does not come with any. Please use files you have the right to
  use, within the rules that apply where you are.
- For questions about a server, please ask the person who runs it.

## If you run a server

- A server reads only the song list (with its jackets and the DJ cards) from your own client data, in a folder or in
  an archive, or from a song list openDMT3 made from it, and keeps it in its `data` folder.
- Players get the launcher from your server's **Download** page, with the accounts you make on the admin pages.
- If a rights holder asks you to take something down, please do so.

## Developers and contributors

- The software is provided "as is", without warranty of any kind, as the license states. To the fullest extent the
  law allows, the authors and contributors are not liable for any claim, damages or other liability arising from it or
  from how anyone uses it.
- Authors and contributors do not supply game files, do not tell anyone where to get them, and do not grant any right
  to use them.
- Each server is run independently by its own owner. This project is not a service and does not run servers on
  anyone's behalf.
- Please use, run and change this software in line with copyright law, the game's terms and the laws where you live,
  and only with game files you have the right to use.
- Contributions come in under the same license.
