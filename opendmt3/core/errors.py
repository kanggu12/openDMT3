"""Errors that a person reads, and their words in English and Korean.

An error keeps its English sentence, str(e), which the command line, the API and the logs show. For the
launcher's windows and the site's pages it also carries a key into TEXT below and the values for the gaps, so a
reader who picked Korean reads it in Korean. An error with no key, or a key missing from TEXT (an API code newer
than this launcher), reads as its English sentence.
"""


class Worded(Exception):
    """An exception with an English sentence and, optionally, the key and values of its words in TEXT."""

    def __init__(self, message, key=None, **params):
        super().__init__(message)
        # The key picks the words; the params fill their {gaps}.
        self.key, self.params = key, params


# key -> (English, Korean). The English entry of an error raised here is the sentence the error itself carries (a
# test checks that every raise site matches), so English readers see the same text everywhere. The error.api
# entries are the launcher's own words for the server's error codes: the server's sentences are written for
# programs (they name API paths), not for players.
TEXT = {
    # The game folder and the files the setup changes (game.GameError).
    "error.game.no_folder": ("no game folder (a folder with the PC client and the game's files) at or below {path}",
                             "{path} 아래에 게임 폴더(PC 클라이언트와 게임 파일이 있는 폴더)가 없습니다."),
    # What a game folder's client is (game.Game.table): the cabinet's, or none that opens the game's files.
    "error.game.cabinet_client": ("The cabinet's client: does not work here, the PC client is needed.",
                                  "기체용 클라이언트: 여기서는 못 씁니다. PC 클라이언트가 필요합니다."),
    "error.game.no_table": ("The game's files cannot be opened with this client.",
                            "이 클라이언트로는 게임 파일을 열 수 없습니다."),
    "error.game.config": ("the file with the game's settings has no {name}",
                          "게임 설정이 든 파일에 {name} 파일이 없습니다."),
    "error.game.server_address": ("server address must be host:port, not {value!r}",
                                  "서버 주소는 host:port 꼴로 적습니다(받은 값: {value!r})."),
    "error.game.no_card_reader": ("openDMT3's card reader is not part of this build",
                                  "이 빌드에는 openDMT3 카드 리더가 들어 있지 않습니다."),
    # The song list, the jackets and the DJ cards read from the game's files (server/services/catalog.py, cards.py).
    "error.game.no_song_list": ("the game's files have no song list", "게임 파일에 곡 목록이 없습니다."),
    "error.game.damaged.songs": ("The file with the song list is damaged. Copy the game folder again, or unpack the "
                                 "archive again.",
                                 "곡 목록이 든 파일이 손상됐습니다. 게임 폴더를 다시 복사하거나 압축 파일을 다시 푸세요."),
    "error.game.damaged.jackets": ("The file with the jackets is damaged. Copy the game folder again, or unpack the "
                                   "archive again.",
                                   "자켓이 든 파일이 손상됐습니다. 게임 폴더를 다시 복사하거나 압축 파일을 다시 푸세요."),
    "error.game.damaged.cards": ("The file with the DJ cards is damaged. Copy the game folder again, or unpack the "
                                 "archive again.",
                                 "DJ 카드가 든 파일이 손상됐습니다. 게임 폴더를 다시 복사하거나 압축 파일을 다시 푸세요."),
    "error.game.no_jackets": ("the game's files have no jackets", "게임 파일에 자켓이 없습니다."),
    "error.game.no_file": ("the game folder has no file this part is in", "게임 폴더에 이 부분이 든 파일이 없습니다."),
    "error.game.permission": ("the game's files cannot be read by this user", "이 사용자는 게임 파일을 읽을 수 없습니다."),
    "error.game.damaged": ("One of the game's files is damaged. Copy the game folder again, or unpack the archive again.",
                           "게임 파일 하나가 손상됐습니다. 게임 폴더를 다시 복사하거나 압축 파일을 다시 푸세요."),
    "error.game.not_chosen": ("no game folder chosen yet", "아직 게임 폴더를 고르지 않았습니다."),
    "error.game.open_change": ("the game is open: close it before changing its files",
                               "게임이 열려 있습니다. 게임 파일을 바꾸기 전에 게임을 닫아 주세요."),
    "error.game.another_play": ("Another openDMT3 is getting the game ready or playing it. Wait until that game closes.",
                                "다른 openDMT3가 게임을 준비하거나 플레이하고 있습니다. 그 게임이 닫힐 때까지 기다리세요."),
    "error.game.needs_host": ("playing on this PC needs the built-in server",
                              "이 PC에서 플레이하려면 내장 서버가 필요합니다."),
    "error.game.open_restore": ("the game is open: close it before putting its files back",
                                "게임이 열려 있습니다. 파일을 되돌리기 전에 게임을 닫아 주세요."),
    "error.game.original_missing": ("the original of {path} is not in backup\\ any more",
                                    "backup에 {path}의 원본이 더는 없습니다."),
    # The records page on this PC's site (launcher.actions.records_link).
    "error.records.mode": ("the records page is for playing on this PC",
                           "기록 페이지는 이 PC에서 플레이할 때 씁니다."),
    "error.records.guest": ("choose a player first: a guest has no records page",
                            "먼저 플레이할 사람을 고르세요. 손님은 기록 페이지가 없습니다."),
    "error.records.no_site": ("this launcher cannot show the records page (its web libraries are missing)",
                              "이 런처는 기록 페이지를 띄울 수 없습니다(웹 라이브러리가 없습니다)."),
    "error.records.no_player": ("{login_id} is not a player on this PC", "이 PC에 없는 플레이어입니다: {login_id}"),
    "error.records.signin": ("sign in on the Online page first", "먼저 온라인 페이지에서 로그인하세요."),
    "error.records.old_server": ("this server is too old for the Records page",
                                 "이 서버는 기록 페이지를 보여 주기에 너무 오래된 버전입니다."),
    "error.records.offline": ("records are kept when playing on this PC or on another server, not offline",
                              "기록은 이 PC나 다른 서버에서 플레이할 때 남습니다. 오프라인에서는 남지 않습니다."),
    # Shortcuts and starting with Windows (client/shortcuts.py).
    "error.shortcut.installed": ("only the installed launcher on Windows can make this",
                                 "설치한 런처(Windows)에서만 만들 수 있습니다."),
    "error.shortcut.failed": ("Windows did not make the shortcut: {reason}", "Windows가 바로 가기를 만들지 못했습니다: {reason}"),
    # The command line's own (client/main.py).
    "error.cli.password": ("no password: give it on standard input", "비밀번호가 없습니다. 표준 입력으로 주세요."),
    "error.cli.no_server": ("connect to a server first (--server URL)", "먼저 서버에 연결하세요(--server URL)."),
    # Removing openDMT3 (client/leaving.py).
    "error.remove.still_changed": ("game files that did not go back: {n}; the note README-openDMT3.txt in the game "
                                   "folder's backup names them",
                                   "게임 파일 {n}개가 원래대로 돌아가지 않았습니다. 게임 폴더 backup의 README-openDMT3.txt에 적어 두었습니다."),
    # Accounts, on the launcher's Online page and the site's admin pages (services.accounts.AccountError).
    "error.account.id": ("an ID is 1 to {max} letters or digits (what the game's keypad can type)",
                         "ID는 영문자와 숫자로 1~{max}자입니다(게임 키패드로 입력할 수 있는 글자)."),
    "error.account.password": ("a password is {min} to {max} letters or digits",
                               "비밀번호는 영문자와 숫자로 {min}~{max}자입니다."),
    "error.account.dj": ("a DJ name is 1 to {max} characters", "DJ 이름은 1~{max}자입니다."),
    "error.account.taken": ("the ID {login_id} is taken", "이미 쓰이는 ID입니다: {login_id}"),
    # The server keeps an enabled admin: its last one is never disabled nor loses the rights (accounts.set_admin,
    # accounts.set_disabled), on the admin pages and through the API alike.
    "error.account.last_admin": ("the server needs an enabled admin, and {login_id} is the only one",
                                 "서버에는 활성화된 관리자가 있어야 하는데 {login_id} 한 명뿐입니다."),
    # The notice at the top of every page of the site (services.notice.NoticeError).
    "error.notice.long": ("a notice is one line of up to {max} characters", "공지는 {max}자까지 한 줄로 씁니다."),
    # The DJ card's choices (services.cards.CardError).
    "error.card.tables": ("the game's files have no DJ cards", "게임 파일에 DJ 카드가 없습니다."),
    "error.card.icon": ("there is no icon {number}", "그런 아이콘이 없습니다: {number}"),
    "error.card.plate": ("there is no plate {number}", "그런 플레이트가 없습니다: {number}"),
    "error.card.pattern": ("there is no plate pattern {number}", "그런 플레이트 패턴이 없습니다: {number}"),
    "error.card.comment": ("a comment is up to {max} characters", "코멘트는 {max}자까지 씁니다."),
    # The API's named tokens, on the Account page and through the API (services.tokens.TokenError).
    "error.token.name": ("a token's name is 1 to {max} characters", "토큰 이름은 1~{max}자입니다."),
    "error.token.scope": ("a token's scope is read or write", "토큰 권한은 read 또는 write입니다."),
    "error.token.many": ("an account holds at most {most} tokens: revoke one first",
                         "계정마다 토큰은 {most}개까지입니다. 먼저 하나를 폐기하세요."),
    "error.token.unknown": ("no token {id} on this account", "이 계정에 그런 토큰이 없습니다: {id}"),
    "error.token.read_only": ("a read-only token makes GET calls only, and none of an admin's",
                              "읽기만 하는 토큰은 GET 호출만 하며 관리자의 호출은 하지 못합니다."),
    # What a path on the server PC is, and the archives it opens (server/services/sources.py, SourceError).
    "error.source.nothing": ("This is neither a game folder nor an archive holding one.",
                             "게임 폴더도, 게임이 든 압축 파일도 아닙니다."),
    "error.source.part": ("This is part of a game folder. Choose the whole game folder.",
                          "게임 폴더의 일부입니다. 게임 폴더 전체를 고르세요."),
    "error.source.later_part": ("This is part {n} of a split archive. Put every part in one folder and choose the "
                                "first.",
                                "분할 압축의 {n}번째 조각입니다. 모든 조각을 한 폴더에 두고 첫 조각을 고르세요."),
    "error.source.missing_part": ("Part {n} of this split archive is missing. Put every part in one folder.",
                                  "분할 압축의 {n}번째 조각이 없습니다. 모든 조각을 한 폴더에 두세요."),
    "error.source.password": ("This archive has a password. Enter it.", "압축 파일에 암호가 걸려 있습니다. 암호를 넣으세요."),
    "error.source.wrong_password": ("That is not this archive's password. Enter it again.",
                                    "압축 파일의 암호가 아닙니다. 다시 넣으세요."),
    "error.source.damaged": ("This archive is damaged or not fully downloaded. Download it again.",
                             "압축 파일이 손상됐거나 덜 받아졌습니다. 다시 받으세요."),
    "error.source.entry": ("An entry in this archive cannot be taken: {name}",
                           "압축 파일 안의 항목을 받아들일 수 없습니다: {name}"),
    "error.source.stream": ("This archive says its size only at its end, where it cannot be checked first. Unpack it "
                            "with another program, then choose what came out.",
                            "이 압축 파일은 크기를 끝에만 적어 두어 미리 확인할 수 없습니다. 다른 프로그램으로 푼 뒤 나온 것을 "
                            "고르세요."),
    "error.source.no_7zip": ("Opening this archive needs 7-Zip on the server PC (the server's Docker image has it).",
                             "이 압축 파일을 열려면 서버 PC에 7-Zip이 있어야 합니다(서버의 Docker 이미지에는 들어 있습니다)."),
    "error.source.space": ("Not enough free space to take out what the server needs ({need} needed, {free} free).",
                           "서버에 필요한 파일을 꺼낼 공간이 모자랍니다(필요한 공간 {need}, 남은 공간 {free})."),
    "error.source.unreadable": ("This cannot be read by the server ({reason}).",
                                "서버가 읽을 수 없습니다({reason})."),
    # A song list the launcher saved, uploaded to the server or given to ./dmt3 catalog (songlist.SongListError).
    "error.songlist.not_ours": ("This is not a song list saved by openDMT3.", "openDMT3가 저장한 곡 목록이 아닙니다."),
    "error.songlist.newer": ("This song list was saved by a newer openDMT3 (format {format}; this server reads up to "
                             "{most}).",
                             "더 새 openDMT3가 저장한 곡 목록입니다(형식 {format}, 이 서버는 {most}까지 읽습니다)."),
    "error.songlist.entry": ("An entry in this song list cannot be taken: {name}",
                             "곡 목록 안의 항목을 받아들일 수 없습니다: {name}"),
    "error.songlist.too_large": ("An uploaded song list is at most {mb} MB.", "올리는 곡 목록은 {mb} MB까지입니다."),
    "error.songlist.unpacked": ("This song list holds more than {mb} MB unpacked.",
                                "이 곡 목록은 풀면 {mb} MB가 넘습니다."),
    "error.songlist.entries": ("This song list holds more than {n} entries. Save it again in the launcher.",
                               "이 곡 목록은 항목이 {n}개가 넘습니다. 런처에서 다시 저장하세요."),
    "error.songlist.shape": ("The song list's {part} is not as openDMT3 saves it ({detail}).",
                             "곡 목록의 {part} 부분이 openDMT3가 저장한 꼴이 아닙니다({detail})."),
    "error.songlist.picture": ("A picture in this song list cannot be taken: {name} ({detail}).",
                               "곡 목록 안의 그림을 받아들일 수 없습니다: {name} ({detail})."),
    "error.songlist.counts": ("The song list does not hold what it says it holds ({detail}).",
                              "곡 목록에 든 것이 적힌 것과 다릅니다({detail})."),
    "error.songlist.damaged": ("This song list is damaged. Save it again in the launcher.",
                               "곡 목록이 손상됐습니다. 런처에서 다시 저장하세요."),
    "error.songlist.no_file": ("No song list came with the upload.", "올린 곡 목록이 없습니다."),
    "error.songlist.no_pillow": ("This server cannot check pictures: it has no Pillow.",
                                 "이 서버는 그림을 확인할 수 없습니다. Pillow가 없습니다."),
    # The database's backups (services.backups.BackupError).
    "error.backup.unknown": ("no backup named {name}", "그런 이름의 백업이 없습니다: {name}"),
    "error.backup.newer": ("{name} is from a newer openDMT3", "더 새 openDMT3에서 만든 백업입니다: {name}"),
    # A database file the admin uploads to the Backups tab, or through the API (backups.check_upload, too_large,
    # no_file).
    "error.backup.not_sqlite": ("the file is not an SQLite database", "SQLite 데이터베이스 파일이 아닙니다."),
    "error.backup.damaged": ("the file is damaged (SQLite's integrity check did not pass)",
                             "파일이 손상되었습니다(SQLite 무결성 검사를 통과하지 못했습니다)."),
    "error.backup.not_ours": ("the file is not an openDMT3 database: its tables are not this project's",
                              "openDMT3 데이터베이스가 아닙니다. 테이블이 이 프로젝트의 것과 다릅니다."),
    "error.backup.too_new": ("the file is from a newer openDMT3 (database version {version}; this server opens up to "
                             "{most})",
                             "더 새 openDMT3에서 만든 파일입니다(데이터베이스 버전 {version}, 이 서버는 {most}까지 엽니다)."),
    "error.backup.too_large": ("an uploaded backup is at most {mb} MB", "올리는 백업은 {mb} MB까지입니다."),
    "error.backup.no_file": ("no database file came with the upload", "올린 데이터베이스 파일이 없습니다."),
    # The server the launcher runs on this PC (launcher.hosting.HostingError).
    "error.host.timeout": ("the built-in server did not start within {seconds} seconds",
                           "내장 서버가 {seconds}초 안에 시작되지 않았습니다."),
    "error.host.db": ("the server's database cannot be opened", "서버 데이터베이스를 열 수 없습니다."),
    "error.host.db.newer": ("The server's database is from a newer openDMT3. Install the newer launcher again.",
                            "서버 데이터베이스가 더 새로운 openDMT3에서 만든 것입니다. 새 버전 런처를 다시 설치하세요."),
    "error.host.port": ("port {port} on this PC is taken; close the other server",
                        "이 PC의 {port}번 포트를 다른 프로그램이 쓰고 있습니다. 다른 서버를 닫아 주세요."),
    # Another PC's server (launcher.remote.RemoteError).
    "error.remote.empty": ("type the server's address", "서버 주소를 입력해 주세요."),
    "error.remote.address": ("{address!r} is not an address", "주소로 읽을 수 없습니다: {address!r}"),
    "error.remote.unreachable": ("Cannot reach {base}. Check the address and the network.",
                                 "{base}에 연결할 수 없습니다. 주소와 네트워크를 확인하세요."),
    "error.remote.not_opendmt3": ("{base} is not an openDMT3 server", "openDMT3 서버가 아닙니다: {base}"),
    "error.remote.unknown_host": ("Cannot find {host}. Check the address.", "{host} 서버를 찾을 수 없습니다. 주소를 확인하세요."),
    "error.remote.answered": ("the server answered {status}", "서버가 {status} 오류로 답했습니다."),
    "error.remote.not_an_answer": ("{base} did not answer as an openDMT3 server does",
                                   "{base}의 응답이 openDMT3 서버의 응답이 아닙니다."),
    "error.api.wrong_sign_in": ("That ID and password do not match an account.", "ID 또는 비밀번호가 맞지 않습니다."),
    "error.api.too_many_tries": ("Too many sign-ins from this PC, or too many wrong passwords for this ID. Wait a few "
                                 "minutes and try again.",
                                 "이 PC에서 로그인을 너무 많이 했거나 이 ID로 틀린 비밀번호가 너무 많았습니다. 몇 분 "
                                 "뒤에 다시 시도하세요."),
    "error.api.sign_in": ("The server no longer takes your sign-in. Sign in again.",
                          "서버가 로그인을 더 받지 않습니다. 다시 로그인해 주세요."),
    "error.api.unknown_player": ("This server has no such player.", "이 서버에 그런 플레이어가 없습니다."),
    "error.api.admin_only": ("Only an admin of this server can send it a song list.",
                             "이 서버의 관리자만 곡 목록을 보낼 수 있습니다."),
    "error.api.too_large": ("The song list is larger than this server takes.", "곡 목록이 이 서버가 받는 크기보다 큽니다."),
    "error.api.busy": ("The server is importing a song list already. Send it again in a moment.",
                       "서버가 이미 곡 목록을 가져오는 중입니다. 잠시 뒤에 다시 보내세요."),
    # Help, Repair and --repair (client/repair.py).
    "error.repair.not_installed": ("repair works in the launcher installed by openDMT3-win-Setup.exe",
                                   "복구는 openDMT3-win-Setup.exe로 설치한 런처에서 됩니다."),
    "error.repair.no_package": (
        "the installed package is not on this PC (run openDMT3-win-Setup.exe again and choose Repair)",
        "설치된 패키지가 이 PC에 없습니다. openDMT3-win-Setup.exe를 다시 실행해 복구를 고르세요."),
    "error.repair.package": (
        "the installed package cannot be read (run openDMT3-win-Setup.exe again and choose Repair)",
        "설치된 패키지를 읽을 수 없습니다. openDMT3-win-Setup.exe를 다시 실행해 복구를 고르세요."),
    # An update whose package lacks the project's signature (client/updates.py).
    "error.update.unsigned": ("the update to {version} is not signed by the openDMT3 project, so it was not put in",
                              "{version} 업데이트에 openDMT3 프로젝트의 서명이 없어 설치하지 않았습니다."),
    # An update that could not be fetched: no answer, a file cut short, no room (client/updates.py).
    "error.update.download": ("The update to {version} could not be downloaded. Check the connection and try again.",
                              "{version} 업데이트를 내려받지 못했습니다. 연결을 확인하고 다시 해 보세요."),
}


def say(error, language="en"):
    """What `error` says in `language` ("en" or "ko"), as a sentence for a window or a page: the English sentences
    (written for logs and the command line, in lower case and with no full stop) start with a capital there and
    end with a full stop, as the sentences around them do."""
    words = TEXT.get(getattr(error, "key", None))
    if words is None and isinstance(error, OSError) and error.strerror:
        # The system's reason and the file it is about, as written: not Python's "[Errno 13] ..." with each backslash
        # doubled (the system writes the reason in the language Windows is shown in).
        if error.filename:
            return sentence("%s: %s" % (error.strerror, error.filename))
        return closed(sentence(error.strerror), {})
    if words is None:
        # No key, or one this build has no words for: the error's own sentence, which may end with anything.
        return sentence(str(error))
    english, korean = words
    params = getattr(error, "params", {})
    # A missing Korean entry falls back to English, as everywhere else.
    text = (korean if language == "ko" and korean else english).format(**params)
    return closed(sentence(text), params)


def closed(text, params):
    """`text` with a full stop, unless it has its own end or ends with one of its values: after an address, a
    name or a path a full stop would read as part of it."""
    if not text or text[-1] in ".!?:":
        return text
    if any(text.endswith(shown) for value in params.values() for shown in (str(value), repr(value)) if shown):
        return text
    last = text.rsplit(" ", 1)[-1]
    if "\\" in last or "/" in last:
        # It ends with a path or an address of its own.
        return text
    return text + "."


def sentence(text):
    """A capital at the start, unless the first word is an address or a name that is written in lower case."""
    first = text.split(" ", 1)[0]
    if not text[:1].islower() or "://" in first or first.startswith("openDMT3"):
        return text
    return text[0].upper() + text[1:]
