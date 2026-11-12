# The game's protocol

What TECHNIKA 3's client (the build that runs on a PC) and its server exchange, as openDMT3's server implements it
(`opendmt3/server/`). Everything here was read from how the client builds and reads its messages and checked
against the client itself; where a field's meaning is still a guess, it says so.

## Messages

One TCP connection to the address in the client's network settings (port 4725 by default). A message is:

| Offset | Size | What |
|---|---|---|
| 0 | 1 | Header: which message it is |
| 1 | 7 | Unused (left at zero by the server) |
| 8 | the rest | Body |

There is no length field: each header has one fixed size, known to both sides (`opendmt3/server/messages.py`).
The client drops the connection on a header it does not know. One client message, 0x55, carries its own total size
as a 16-bit value at offset 2.

## The cipher

Every message is encrypted whole, in both directions:

- TEA, 32 rounds, over each 8-byte block (little-endian words). The bytes after the last whole block are XORed
  with the low byte of the first key word plus their place in that tail.
- The 128-bit key is four consecutive words of the standard CRC-32 table (polynomial 0xEDB88320), starting at
  `(state XOR 0x0A030110) mod 252`.
- Each direction has its own state, which moves on after every message: client to server `state * 7 XOR
  0x93783891`, server to client `state * 31 XOR 0xAABBCCDE` (both modulo 2^32).
- Both states start at 0. The handshake request carries a seed that restarts them: the client-to-server state
  becomes the client's step applied to the seed, the server-to-client state the server's step applied to it.

Because blocks are independent, a receiver decrypts the first 8 bytes alone to read the header, and from it the
size of the whole message.

## Connecting

| # | Who | Header | Size | What |
|---|---|---|---|---|
| 1 | server | 0x01 | 14 | Handshake request: the seed (u32 at 8) and two places in the CRC table (u8 at 12, 13), under state 0 |
| 2 | client | 0x02 | 48 | Answer: a machine value (u32 at 8), the two table words asked for (at 12, 16), an 8-byte machine key masked with `(word1 << 7) OR word0` (at 20), the client's version text (20 bytes at 28) |
| 3 | server | 0x03 | 61 | Result: 1 at offset 8 lets the client online (its NET light turns green); a name (20 bytes at 9), a group number (u32 at 29) and a group name (20 bytes at 33) |
| 4 | client | 0x5E | 8 | The client is online |

The server must send nothing between 0x01 and the client's 0x02: the client restarts its states from the seed on
its main thread. After that the client sends 0x0A about every 11 seconds and drops the connection if 0x0B does
not come back within about a minute; the server sends 0x06 (openDMT3 every 10 seconds) and the client answers 0x07.

openDMT3 closes a connection whose 0x02 has not come within 10 seconds, and one that sent no whole message for 90
seconds. One address holds at most 16 connections and sends at most 64 KB a minute over all of them (a new
connection counts as 1 KB of it).

## Logging in

The PC client logs players in by card only (its ID screens are never reached). The card reader
library gives the game a 20-character card number; openDMT3's stand-in (`native/cardreader/`, also its in-game
layer) reads it from a file the launcher writes.

| Who | Header | Size | What |
|---|---|---|---|
| client | 0x60 | 28 | Card login: the card number (20 bytes at 8) |
| server | 0x1E | 8 | Empties the client's list of the player's records (the last player's too) |
| server | 0x5A | 23 | One of the player's records, for the song select: mode (u8 at 8), song (u32 at 9), pattern (u8 at 13), trophy (u8 at 14: 0 none, 1 bronze, 2 silver, 3 gold, 4 all combo), score (u32 at 15), max combo (u32 at 19) |
| server | 0x65 | 166 | The player (below) |
| server | 0x64 | 9 | The result (u8 at 8): 0x07 succeeded; 0x0E failed (the client shows a failed login and tries again) |
| server | 0x66 | 8 | Empties the client's first-place lists (one per mode) |
| server | 0x5F | 39 | One chart's first place, for the song select: mode (u32 at 8, 0 to 4 only), song (u32 at 12), pattern (u8 at 16), score (u32 at 17), DJ name (UTF-16LE, 9 characters, at 21) |

The answer comes in this order: the player's records (0x1E, then a 0x5A per chart), the player (0x65), the result
(0x64), then every chart's first place on the server (0x66, then a 0x5F per chart). An unknown card, a disabled
account's, and every card while the server is in maintenance get the result alone: 0x64 with 0x0E. The connection
stays online. The client takes the records
over as it reads 0x65, and shows the DJ card on its success screen. The song select then shows, for the chart under
the cursor, BEST RECORD with its DJ, MY RECORD, MAX COMBO and a trophy on the tile. openDMT3 sends the records of
STAR and POP (the modes the client keeps them for) with no trophy and a max combo of 0: the results do not say
them yet.

0x65, as the client reads it from its body (the message after the 8-byte head):

| Offset | Size | What |
|---|---|---|
| 8 | 4 | The player's number |
| 16 | 4 | Experience: the client shows the level its own table gives it |
| 20 | 18 | The DJ name, UTF-16LE, 9 characters with the closing zero (a name at 12 showed from its fifth character on) |
| 42 | 4 | The icon, by the game's icon table (0 is the no-card silhouette, 1 the basic DJ icon) |
| 46 | 4 | The title plate: the plate's number low (from 32768), a pattern drawn over it high (0 for none), by the game's title tables; a number in neither leaves the "NEED IDCARD" plate |
| 50 | 4 | The comment's letters: 1 white with an outline; 0 draws them clear |
| 54 | 24 | The comment over the plate, UTF-16LE, up to 12 characters |
| 78 | 4 | The note skin, from the client's code (a folder 0 to 12; a number with no folder crashed the client) |
| 82 | 4 | MAX points, beside the name on the song select |
| 86 | 4 | The crew, from the client's code (0: none; the crew's name, emblem and points follow it) |

openDMT3 sends the experience of the stages cleared, the player's icon, plate, pattern and comment (chosen on the
site, from the numbers the game's tables have pictures for), and zero for the rest. Each value was checked on the
client's screen; Hangul shows in the name, the comment and a first place's DJ name.
After a login the client asks the server nothing until it plays: songs and patterns come from its own song lists.

## Results

When a session ends the client sends 0x78 (120), 0x79 (16), 0x7A (16), 0x7B (20) and 0x6E (155) together and
expects no answer. openDMT3 keeps 0x6E:

| Offset | Size | What |
|---|---|---|
| 8 | 4 | The player's number (from 0x65) |
| 12 | 1 | Mode (0 is STAR; others not confirmed yet) |
| 13 | 1 | Whether the last stage was cleared |
| 14 | 47 x 3 | One record per cleared stage; an unused slot has song number 0 |

In a record: song number (u32 at 0), pattern (u8 at 4), score (u32 at 7), seven 16-bit counts at 15 (judgements;
which count is which is not confirmed yet). openDMT3 keeps the 47 bytes as sent beside the fields it reads.

openDMT3 keeps a record only when the client can have sent it: one of the client's modes (0 to 4: STAR, POP, CLUB,
CREW RACE, CREW CHALLENGE), a pattern from 1 to 4 (the song list's four per mode), and, when the server has a song
list, one of its songs. It keeps at most 8 stages for one card login: a credit's results come once, in one 0x6E of
three slots, and how many stages a credit holds is not known, so the cap is a structural one with room to spare.
The score is kept as sent; no maximum is known. With a song list, only its songs go out in 0x5A and 0x5F.

## Everything the client registers

The server-to-client headers the client accepts, with their sizes, and the client-to-server ones it sends, are the
`TO_CLIENT` and `TO_SERVER` tables in `opendmt3/server/messages.py`. A header without a handler is named in the
server's log once per connection, and with `--verbose` every one is logged with its first bytes, which is how new
ones get worked out; the login messages (0x60, 0x61 and 0x62, which carry a card number or a password's digest) never
show their bytes, there or on the admin's log page. Until the handshake has let a client online, the server reads
nothing but its 0x02.
