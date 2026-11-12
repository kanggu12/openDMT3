"""The site's words, in English and Korean (English unless the visitor picks Korean; a cookie keeps the choice).

The words of errors are in errors.py, shared with the launcher.
"""

import re

from opendmt3.core import errors

TEXT = {
    "site.tagline": ("Open-source TECHNIKA 3 project", "오픈소스 TECHNIKA 3 프로젝트"),
    "nav.home": ("HOME", "HOME"),
    "nav.rankings": ("RANKINGS", "RANKINGS"),
    "nav.songs": ("SONGS", "SONGS"),
    "nav.download": ("DOWNLOAD", "DOWNLOAD"),
    "nav.admin": ("ADMIN", "ADMIN"),
    "nav.signout": ("Sign out", "로그아웃"),
    "signin.title": ("Sign in", "로그인"),
    "signin.text": ("With the ID and password from this server's owner.", "이 서버 운영자에게 받은 ID와 비밀번호로 로그인하세요."),
    "signin.made": ("Made {login_id}. Sign in with it.", "{login_id} 계정을 만들었습니다. 이 계정으로 로그인하세요."),
    "signin.id": ("ID", "ID"),
    "signin.password": ("Password", "비밀번호"),
    "signin.button": ("Sign in", "로그인"),
    "signin.wrong": ("That ID and password do not match an account.", "ID 또는 비밀번호가 맞지 않습니다."),
    "signin.down": ("Sign-in is not available right now. Try again in a while.",
                    "지금은 로그인할 수 없습니다. 잠시 뒤에 다시 시도하세요."),
    "signin.wait": ("Too many tries from this address. Wait a few minutes.", "이 주소에서 너무 많이 시도했습니다. 몇 분 뒤에 다시 시도하세요."),
    "signin.wait.id": ("Too many wrong passwords for this ID. Wait a few minutes.",
                       "이 ID로 틀린 비밀번호가 너무 많았습니다. 몇 분 뒤에 다시 시도하세요."),
    "owner.title": ("Make the owner's account", "운영자 계정 만들기"),
    "owner.text": ("This server has no account yet. The first one is the owner's, with the admin pages. Only this PC "
                   "sees this page.",
                   "이 서버에는 아직 계정이 없습니다. 처음 만드는 계정이 운영자 계정이며 관리 페이지를 쓸 수 있습니다. 이 페이지는 서버 PC에서만 보입니다."),
    "owner.hint": ("ID: up to 8 letters and digits. DJ name: up to 8 characters, shown in the game. Password: {min} "
                   "to {max} letters and digits.",
                   "ID는 영문·숫자 8자까지, DJ 이름은 8자까지이고 게임에 보입니다. 비밀번호는 영문·숫자 {min}~{max}자입니다."),
    "owner.button": ("Make the account", "계정 만들기"),
    "account.id": ("ID", "ID"),
    "account.password": ("Password", "비밀번호"),
    "account.dj": ("DJ name", "DJ 이름"),
    "account.admin": ("Admin rights", "관리자 권한"),
    "account.password.auto": ("(auto)", "(자동)"),
    "home.dj": ("Your DJ", "내 DJ"),
    "home.card": ("Card", "카드"),
    "home.card.text": ("The launcher puts this card in when you play, so the game logs you in.",
                       "플레이할 때 런처가 이 카드를 꽂아 주어 게임에 바로 로그인됩니다."),
    "home.cabinets": ("Connected cabinets", "접속 중인 기체"),
    "home.cabinets.none": ("No cabinet is connected.", "접속 중인 기체가 없습니다."),
    "home.cabinet.free": ("Free", "비어 있음"),
    "home.cabinet.playing": ("{dj} is playing", "{dj} 플레이 중"),
    "home.mine": ("Your recent plays", "내 최근 플레이"),
    "home.everyone": ("Recent plays on this server", "이 서버의 최근 플레이"),
    "home.top": ("Top DJs, {mode}", "{mode} 상위 DJ"),
    "home.top.all": ("The whole ranking", "전체 랭킹 보기"),
    "home.records": ("New records", "새 기록"),
    "home.records.none": ("No new record yet. A play that beats its player's own best on a chart shows here.",
                          "아직 새 기록이 없습니다. 자기 최고 점수를 넘은 플레이가 여기에 나옵니다."),
    "home.records.before": ("Best before: {score}", "이전 최고 점수: {score}"),
    "home.new.title": ("A new best on this chart when it was played", "플레이했을 때 이 차트의 새 최고 점수"),
    "list.latest": ("The latest {n} of {of}", "전체 {of}개 중 최근 {n}개"),
    "list.top": ("Top {n} of {of}", "전체 {of} 중 상위 {n}위까지"),
    "home.plays.none": ("No play yet. Cleared stages show here after a session.", "아직 플레이 기록이 없습니다. 게임을 마치면 클리어한 스테이지가 여기에 나옵니다."),
    "home.score": ("Score", "점수"),
    "home.pattern": ("Pattern {n}", "패턴 {n}"),
    "home.get": ("Play on your PC", "내 PC에서 플레이"),
    "home.get.text": ("Download the launcher here: it opens on this server, and you sign in with your ID.",
                      "이 사이트에서 받은 런처에는 이 서버 주소가 들어 있습니다. 내 ID로 로그인하세요."),
    "download.title": ("Download", "다운로드"),
    "download.sub": ("The openDMT3 launcher for Windows. It gets your game ready, logs you in to this server and "
                     "starts the game.",
                     "Windows용 openDMT3 런처입니다. 게임을 준비하고 이 서버에 로그인해 게임을 시작합니다."),
    "download.button": ("Download openDMT3 for Windows", "Windows용 openDMT3 다운로드"),
    "download.none": ("This server has no installer to hand out.", "이 서버에는 나눠 줄 설치 파일이 없습니다."),
    "download.steps": ("Then", "그다음"),
    "download.step1": ("Run {file}. If Windows says it protected your PC: More info, then Run anyway.",
                       "{file}를 실행하세요. Windows가 PC를 보호했다고 하면 '추가 정보', '실행'을 누르세요."),
    "download.step1.none": ("Get openDMT3-win-Setup.exe from the project's releases and run it. If Windows says it "
                            "protected your PC: More info, then Run anyway.",
                            "프로젝트 릴리스에서 openDMT3-win-Setup.exe를 받아 실행하세요. Windows가 PC를 보호했다고 하면 '추가 정보', '실행'을 누르세요."),
    "download.facts": ("{size} MB, put on this server {when}", "{size} MB, {when}에 이 서버에 올렸습니다."),
    "download.facts.version": ("Version {version}, {size} MB, put on this server {when}",
                               "버전 {version}, {size} MB, {when}에 이 서버에 올렸습니다."),
    "download.step2": ("The launcher it installs opens on this server ({address}): on LOG IN (or Online), press "
                       "Connect.",
                       "설치된 런처에는 이 서버 주소({address})가 들어 있습니다. LOG IN(또는 온라인)에서 '연결'을 누르세요."),
    "download.step2.none": ("On LOG IN (or Online), choose Another server, type the address ({address}) and press "
                            "Connect.",
                            "LOG IN(또는 온라인)에서 '다른 서버'를 고르고 주소({address})를 입력한 뒤 '연결'을 누르세요."),
    "download.step3": ("Sign in with your ID ({login_id}) and press PLAY.", "내 ID({login_id})로 로그인하고 PLAY를 누르세요."),
    "download.need": ("You need your own TECHNIKA 3 client data; openDMT3 has no game files.",
                      "TECHNIKA 3 클라이언트 데이터를 직접 가지고 있어야 합니다. openDMT3에는 게임 파일이 없습니다."),
    "rankings.sub": ("Each mode's DJs, by the total of their best scores, by the average of their best 30, or by "
                     "this month's total.",
                     "모드별 DJ 랭킹입니다. 최고 점수의 총점, 최고 30차트 평균, 이번 달 총점으로 봅니다."),
    "rankings.none": ("No cleared stage yet.", "아직 클리어한 스테이지가 없습니다."),
    "rankings.total": ("Total score", "총점"),
    "rankings.charts": ("Charts", "차트"),
    "rankings.charts.n": ("{n} charts", "차트 {n}개"),
    "rankings.dj": ("DJ", "DJ"),
    "rankings.you": ("You", "나"),
    "songs.sub": ("Every song on this server, and its best score.", "이 서버의 모든 곡과 최고 점수입니다."),
    "songs.search": ("Song or composer", "곡이나 작곡가"),
    "songs.find": ("Find", "찾기"),
    "songs.song": ("Song", "곡"),
    "songs.plays": ("Plays", "플레이"),
    "songs.players": ("Players", "플레이어"),
    "songs.best": ("Best", "최고 점수"),
    "songs.none": ("No song yet: they show once the server's owner imports the song list, and played songs show here "
                   "too.",
                   "아직 곡이 없습니다. 서버 운영자가 곡 목록을 가져오면 곡이 나옵니다. 플레이한 곡도 여기 나옵니다."),
    "songs.nomatch": ("No song matches {query}.", "{query}에 맞는 곡이 없습니다."),
    "songs.count": ("{n} of {of} songs", "{of}곡 중 {n}곡"),
    "song.kicker": ("SONG {n}", "곡 {n}"),
    "song.none": ("Nobody has cleared this song yet.", "아직 이 곡을 클리어한 사람이 없습니다."),
    "rankings.by.total": ("Total", "총점"),
    "rankings.by.best30": ("Best {n} average", "최고 {n}차트 평균"),
    "rankings.best30.hint": ("The average of each DJ's {n} best charts in this mode; charts not cleared yet count as "
                             "0.",
                             "이 모드에서 DJ마다 점수가 가장 높은 차트 {n}개의 평균입니다. 아직 클리어하지 않은 차트는 0점으로 셉니다."),
    "rankings.best30.charts": ("{n} of {of}", "{of}개 중 {n}개"),
    "rankings.by.month": ("This month", "이번 달"),
    "rankings.month.hint": ("The total of each DJ's best score on every chart in {month}, on the server's clock. It "
                            "starts again on the 1st of each month.",
                            "{month}에 DJ마다 차트별 최고 점수를 더한 총점입니다(서버 시각 기준). 매달 1일에 새로 시작합니다."),
    "rankings.month.none": ("No cleared stage in this mode this month yet.",
                            "이번 달에는 이 모드에서 아직 클리어한 스테이지가 없습니다."),
    "rankings.past": ("Past months", "지난 달"),
    "month.name": ("{month} {year}", "{year}년 {month}"),
    "month.1": ("January", "1월"),
    "month.2": ("February", "2월"),
    "month.3": ("March", "3월"),
    "month.4": ("April", "4월"),
    "month.5": ("May", "5월"),
    "month.6": ("June", "6월"),
    "month.7": ("July", "7월"),
    "month.8": ("August", "8월"),
    "month.9": ("September", "9월"),
    "month.10": ("October", "10월"),
    "month.11": ("November", "11월"),
    "month.12": ("December", "12월"),
    "song.chart": ("{mode} · Pattern {n}", "{mode} · 패턴 {n}"),
    "song.chart.level": ("{mode} · Pattern {n} · Lv {level}", "{mode} · 패턴 {n} · Lv {level}"),
    "song.score": ("Score", "점수"),
    "song.when": ("Set", "기록한 때"),
    "dj.kicker": ("openDMT3 · DJ", "openDMT3 · DJ"),
    "dj.plays": ("Cleared stages", "클리어한 스테이지"),
    "dj.songs": ("Songs", "곡"),
    "dj.charts": ("Charts", "차트"),
    "dj.last": ("Last play", "마지막 플레이"),
    "dj.bests": ("Best scores", "최고 점수"),
    "dj.recent": ("Recent plays", "최근 플레이"),
    "dj.activity": ("Stages cleared, last 12 weeks", "최근 12주 클리어 수"),
    "dj.activity.tip": ("{start} to {end}: {n}", "{start}~{end}: {n}"),
    "dj.activity.table": ("As a table", "표로 보기"),
    "dj.activity.week": ("Week", "주"),
    "dj.activity.max": ("most {n}", "최대 {n}"),
    "dj.modes": ("By mode", "모드별"),
    "dj.top": ("Most played", "많이 한 곡"),
    "dj.sessions": ("Sessions", "세션"),
    "dj.time": ("Time played", "플레이 시간"),
    "common.hours": ("{h} h {m} min", "{h}시간 {m}분"),
    "common.minutes": ("{m} min", "{m}분"),
    "dj.none": ("No cleared stage yet.", "아직 클리어한 스테이지가 없습니다."),
    "dj.place": ("{n} / {of}", "{n} / {of}"),
    "dj.place.label": ("{mode} ranking by total", "{mode} 총점 랭킹"),
    "admin.title": ("Admin", "관리"),
    "admin.players": ("Players", "플레이어"),
    "admin.cabinets": ("Cabinets", "기체"),
    "admin.backups": ("Backups", "백업"),
    "admin.status": ("Status", "상태"),
    "admin.song_list": ("Song list", "곡 목록"),
    "admin.log": ("Logs", "로그"),
    "cabinets.none": ("No cabinet has connected yet.", "아직 접속한 기체가 없습니다."),
    "cabinets.name": ("Cabinet", "기체"),
    "cabinets.rename": ("Save name", "이름 저장"),
    "cabinets.renamed": ("The cabinet's name is saved.", "기체 이름을 저장했습니다."),
    "cabinets.now": ("Now", "접속 중"),
    "cabinets.guest": ("no one logged in", "로그인 없음"),
    "cabinets.last": ("Last seen", "마지막 접속"),
    "cabinets.sessions": ("Sessions", "세션"),
    "cabinets.plays": ("Stages", "스테이지"),
    "status.version": ("Version", "버전"),
    "status.started": ("Running since", "시작한 때"),
    "status.connected": ("Connected cabinets", "접속 중인 기체"),
    "status.accounts.all": ("Accounts", "계정"),
    "status.accounts": ("Accounts ({n} disabled)", "계정(비활성화 {n})"),
    "status.cabinets": ("Cabinets seen", "접속했던 기체"),
    "status.today": ("Today", "오늘"),
    "status.week": ("7 days", "7일"),
    "status.month": ("30 days", "30일"),
    "status.plays": ("Stages cleared", "클리어한 스테이지"),
    "status.players": ("Players who cleared", "클리어한 플레이어"),
    "status.sessions": ("Sessions", "세션"),
    "status.time": ("Time played", "플레이 시간"),
    "status.database": ("Database", "데이터베이스"),
    "status.last_backup": ("Last backup", "마지막 백업"),
    "status.no_backup": ("none yet", "아직 없음"),
    "status.game_port": ("Game port", "게임 포트"),
    "notice.bar": ("Notice", "공지"),
    "notice.title": ("Notice", "공지"),
    "notice.label": ("The line every page shows", "모든 페이지에 보일 한 줄"),
    "notice.save": ("Show the notice", "공지 올리기"),
    "notice.clear": ("Clear the notice", "공지 내리기"),
    "notice.since": ("Shown since {when}, by {who}", "{when}부터 · {who}"),
    "notice.hint": ("Up to {max} characters.", "{max}자까지 씁니다."),
    "notice.saved": ("The notice is on every page now.", "공지를 모든 페이지에 올렸습니다."),
    "notice.cleared": ("The notice is cleared.", "공지를 내렸습니다."),
    "maintenance.bar": ("Maintenance", "점검"),
    "maintenance.bar.text": ("The game cannot log in until maintenance ends.", "점검이 끝날 때까지 게임에 로그인할 수 없습니다."),
    "maintenance.title": ("Maintenance", "점검"),
    "maintenance.since": ("On since {when}, by {who}", "{when}부터 점검 중 · {who}"),
    "maintenance.off": ("Off: the cabinets log in as usual.", "점검 중이 아닙니다. 기체에서 평소처럼 로그인합니다."),
    "maintenance.start": ("Start maintenance", "점검 시작"),
    "maintenance.end": ("End maintenance", "점검 끝내기"),
    "maintenance.hint": ("While it is on, the game server refuses every card login: the game shows a failed "
                         "membership authentication. A game being played keeps its results.",
                         "점검 중에는 게임 서버가 모든 카드 로그인을 거절합니다. 게임에는 회원 인증 실패로 나옵니다. 하던 게임의 기록은 남습니다."),
    "maintenance.started": ("Maintenance is on: the game server refuses card logins.",
                            "점검을 시작했습니다. 게임 서버가 카드 로그인을 거절합니다."),
    "maintenance.ended": ("Maintenance is over: the cabinets log in again.", "점검을 끝냈습니다. 기체에서 다시 로그인할 수 있습니다."),
    "status.look": ("To look at", "확인할 것"),
    "status.look.backup": ("No backup in the last {days} days.", "최근 {days}일 동안 백업이 없습니다."),
    "status.look.backup.fix": ("Back up on the Backups tab", "백업 탭에서 백업하기"),
    "status.look.songs": ("No song list: songs show as numbers and the DJ cards have nothing to choose from.",
                          "곡 목록이 없습니다. 곡이 번호로 나오고 DJ 카드에서 고를 것이 없습니다."),
    "status.look.songs.fix": ("Import it on the Song list tab", "곡 목록 탭에서 가져오기"),
    "status.look.installer": ("No installer to hand out on the Download page: put {file} in {folder}.",
                              "다운로드 페이지에서 나눠 줄 설치 파일이 없습니다. {file}를 {folder}에 넣으세요."),
    "status.look.installer.command": ("No installer to hand out on the Download page. On the server PC: ./dmt3 setup "
                                      "--installer FILE",
                                      "다운로드 페이지에서 나눠 줄 설치 파일이 없습니다. 서버 PC에서 ./dmt3 setup --installer FILE을 실행하세요."),
    "status.look.accounts": ("Every account but yours is disabled: nobody else can sign in or play.",
                             "내 계정 말고는 모든 계정이 비활성화되어 있어서 다른 사람은 로그인하거나 플레이할 수 없습니다."),
    "status.look.accounts.fix": ("Enable them on the Players tab", "플레이어 탭에서 활성화하기"),
    # The Status page's Song list card: what the server has of the song list, and where it came from.
    "data.title": ("Song list", "곡 목록"),
    "data.part": ("What", "항목"),
    "data.count": ("How many", "개수"),
    "data.at": ("Last read", "마지막으로 읽은 때"),
    "data.songs": ("Song list", "곡 목록"),
    "data.jackets": ("Jackets", "자켓"),
    "data.cards": ("DJ cards", "DJ 카드"),
    "data.count.songs": ("{n} songs", "곡 {n}개"),
    "data.count.jackets": ("{n} jackets", "자켓 {n}개"),
    "data.count.cards": ("{icon} icons, {plate} plates, {pattern} plate patterns",
                         "아이콘 {icon}개, 플레이트 {plate}개, 플레이트 패턴 {pattern}개"),
    "data.never": ("Not yet", "아직 없음"),
    "data.missing.songs": ("No song list: songs show as numbers, and the DJ card's level counts every chart as level "
                           "1.",
                           "곡 목록이 없습니다. 곡이 번호로 나오고 DJ 카드 레벨은 모든 차트를 1레벨로 셉니다."),
    "data.missing.jackets": ("No jackets: songs show without them.", "자켓이 없습니다. 곡이 자켓 없이 나옵니다."),
    "data.missing.cards": ("No DJ cards: every DJ card keeps the basic icon and plate.",
                           "DJ 카드가 없습니다. 모든 DJ 카드가 기본 아이콘과 플레이트로 나옵니다."),
    "data.missing.why": ("{why}", "{why}"),
    "data.source.folder": ("Last read from the client data in {path}, {when}.",
                           "{when}에 {path}의 클라이언트 데이터에서 읽었습니다."),
    "data.source.archive": ("Last read from the archive {path}, {when}.", "{when}에 압축 파일 {path}에서 읽었습니다."),
    "data.source.file": ("Last taken from a song list ({path}, saved {made}), {when}.",
                         "{when}에 곡 목록({path}, {made}에 저장)에서 가져왔습니다."),
    "data.open": ("Import or upload it on the Song list tab", "곡 목록 탭에서 가져오거나 올리기"),
    # The Song list tab, in the shape of OpenDMTQ's setup page: the thing the server takes, found on the server PC,
    # another folder of it, an upload.
    "songlist.title": ("The song list", "곡 목록"),
    "songlist.lead": ("The song list holds the jackets and the DJ cards too. Please use only files you have the "
                      "right to use.",
                      "곡 목록에는 자켓과 DJ 카드도 들어 있습니다. 쓸 권리가 있는 파일만 써 주세요."),
    "songlist.take.text": ("From the client data on the server PC, in a folder or in an archive (.zip, .7z, .rar; "
                           "split, with every part in one folder), or from a song list the launcher saved. No charts, "
                           "music or videos are read.",
                           "서버 PC에 있는 클라이언트 데이터나 런처가 저장한 곡 목록에서 가져옵니다. 클라이언트 데이터는 폴더도 되고 "
                           "압축 파일(.zip, .7z, .rar, 분할 압축은 모든 조각을 한 폴더에)도 됩니다. 차트, 음악, 영상은 읽지 "
                           "않습니다."),
    "songlist.take.need": ("Without it songs show as numbers and every DJ card keeps the basic icon and plate.",
                           "없으면 곡이 번호로 나오고 모든 DJ 카드가 기본 아이콘과 플레이트로 나옵니다."),
    "songlist.state.ready": ("ready", "쓸 수 있음"),
    "songlist.state.not_yet": ("not yet", "아직 없음"),
    "songlist.found": ("Found on the server PC", "서버 PC에서 찾은 파일"),
    "songlist.found.none": ("Neither client data nor a song list in these folders.",
                            "이 폴더들에서 클라이언트 데이터도, 곡 목록도 찾지 못했습니다."),
    "songlist.found.where": ("Looked in:", "찾아본 곳:"),
    "songlist.found.nowhere": ("This server sees no folder of the server PC to look in.",
                               "이 서버가 찾아볼 수 있는 서버 PC의 폴더가 없습니다."),
    "songlist.import": ("Import", "가져오기"),
    "songlist.import.title": ("Import the song list", "곡 목록 가져오기"),
    "songlist.import.ask": ("Import the song list from {path}?", "{path}에서 곡 목록을 가져올까요?"),
    "songlist.import.detail": ("It replaces the song list, the jackets and the DJ cards this server has.",
                               "이 서버의 곡 목록, 자켓, DJ 카드를 바꿉니다."),
    "songlist.other": ("Another folder on the server PC", "서버 PC의 다른 폴더"),
    "songlist.other.lead": ("Type or paste the path of the folder or file, or click your way to it below, then "
                            "import it.",
                            "폴더나 파일의 경로를 입력하거나 붙여 넣으세요. 아래에서 폴더를 눌러 찾아가도 됩니다."),
    "songlist.other.path": ("Folder or file path", "폴더나 파일 경로"),
    "songlist.other.open": ("Open", "열기"),
    "songlist.other.up": ("Up one folder", "한 단계 위로"),
    "songlist.other.empty": ("No folder in it.", "안에 폴더가 없습니다."),
    "songlist.other.here": ("Import from this folder", "이 폴더에서 가져오기"),
    "songlist.other.path_import": ("Import this path", "이 경로에서 가져오기"),
    "songlist.other.container": ("This server runs in Docker and sees only the folder kept for it. For another "
                                 "folder or file, run this on the server PC:",
                                 "이 서버는 Docker에서 실행 중이라 연결해 둔 폴더만 볼 수 있습니다. 다른 폴더나 파일은 서버 PC에서 이 명령으로 가져오세요:"),
    # The upload fields' own words (templates/_upload.html, site.js), OpenDMTQ's upload box's with the launcher's
    # "Choose ..." for its button; {size} and {max} are filled in on the page.
    "upload.none": ("No file chosen yet", "아직 고른 파일이 없습니다"),
    "upload.drop": (" · or drop the file here", " · 파일을 여기에 끌어다 놓아도 됩니다"),
    "upload.choose": ("Choose a file...", "파일 고르기..."),
    "upload.change": ("Change...", "바꾸기..."),
    "upload.too_big": ("{size}: larger than the {max} limit", "{size}: 제한({max})보다 큽니다"),
    "songlist.upload": ("Upload a song list", "곡 목록 올리기"),
    "songlist.upload.file": ("Song list (openDMT3-song-list.zip)", "곡 목록(openDMT3-song-list.zip)"),
    "songlist.upload.button": ("Upload", "올리기"),
    "songlist.upload.hint": ("A song list the launcher saved (Game page, Save the song list...) or ./dmt3 catalog "
                             "--save made, up to {mb} MB. It replaces the song list, the jackets and the DJ cards "
                             "this server has.",
                             "런처가 저장한 곡 목록(게임 페이지의 '곡 목록 저장...')이나 ./dmt3 catalog --save로 만든 곡 목록을 {mb} MB까지 올립니다. "
                             "이 서버의 곡 목록, 자켓, DJ 카드를 바꿉니다."),
    "songlist.done": ("Imported the song list: {songs} songs.", "곡 목록을 가져왔습니다. 곡 {songs}개입니다."),
    "songlist.busy": ("A song list is being imported already.", "이미 곡 목록을 가져오는 중입니다."),
    "songlist.not_read": ("The song list could not be read. {why}", "곡 목록을 읽지 못했습니다. {why}"),
    "log.changes": ("Changes", "변경 기록"),
    "log.changes.none": ("Nothing changed yet.", "아직 변경 기록이 없습니다."),
    "log.change.cabinet.named": ("named cabinet {0} {1}", "기체 {0}의 이름을 바꿨습니다: {1}"),
    "log.change.account.made": ("made the account {0}", "{0} 계정을 만들었습니다"),
    "log.change.account.password": ("set a new password (and card) for {0}", "{0}의 비밀번호와 카드를 새로 만들었습니다"),
    "log.change.account.named": ("named {0} {1}", "{0}의 DJ 이름을 바꿨습니다: {1}"),
    "log.change.account.card": ("changed the DJ card of {0} ({1})", "{0}의 DJ 카드를 바꿨습니다({1})"),
    "log.change.account.admin_on": ("gave admin rights to {0}", "{0}에게 관리자 권한을 주었습니다"),
    "log.change.account.admin_off": ("took admin rights from {0}", "{0}의 관리자 권한을 뺐습니다"),
    "log.change.account.disabled": ("disabled the account {0}", "{0} 계정을 비활성화했습니다"),
    "log.change.account.enabled": ("enabled the account {0}", "{0} 계정을 활성화했습니다"),
    "log.change.account.deleted": ("deleted the account {0}", "{0} 계정을 삭제했습니다"),
    "log.change.notice.set": ("set the notice: {0}", "공지를 올렸습니다: {0}"),
    "log.change.notice.cleared": ("cleared the notice", "공지를 내렸습니다"),
    "log.change.maintenance.on": ("started maintenance", "점검을 시작했습니다"),
    "log.change.maintenance.off": ("ended maintenance", "점검을 끝냈습니다"),
    "log.change.backup.deleted": ("deleted the backup {0}", "백업을 삭제했습니다: {0}"),
    "log.change.reset.one": ("reset the plays of {0}: {1} gone, backed up as {2}",
                             "{0}의 플레이 기록을 초기화했습니다. 클리어한 스테이지 {1}개를 지우고 백업해 두었습니다: {2}"),
    "log.change.reset.all": ("reset every play: {0} gone, backed up as {1}",
                             "모든 플레이 기록을 초기화했습니다. 클리어한 스테이지 {0}개를 지우고 백업해 두었습니다: {1}"),
    "log.change.token.made": ("made the API token {0} ({1}) for {2}", "{2}의 API 토큰을 만들었습니다: {0} ({1})"),
    "log.change.token.revoked": ("revoked the API token {0} of {1}", "{1}의 API 토큰을 폐기했습니다: {0}"),
    "log.change.backup.made": ("backed up the database as {0}", "데이터베이스를 백업했습니다: {0}"),
    "log.change.backup.restored": ("restored the database from {0}", "데이터베이스를 복원했습니다: {0}"),
    "log.change.backup.uploaded": ("uploaded a backup as {0} ({1} bytes)", "백업을 올렸습니다: {0}({1}바이트)"),
    "log.change.songlist": ("imported the song list from {0}: {1} songs, {2}", "곡 목록을 가져왔습니다: {0}, 곡 {1}개, {2}"),
    "log.change.songlist.uploaded": ("an uploaded song list ({0})", "올린 곡 목록({0})"),
    "log.change.part.nothing missing": ("nothing missing", "빠진 것 없음"),
    "log.change.part.songs missing": ("songs missing", "곡 목록 없음"),
    "log.change.part.jackets missing": ("jackets missing", "자켓 없음"),
    "log.change.part.cards missing": ("cards missing", "DJ 카드 없음"),
    "log.change.part.icon": ("icon", "아이콘"),
    "log.change.part.plate": ("plate", "플레이트"),
    "log.change.part.pattern": ("pattern", "플레이트 패턴"),
    "log.change.part.comment": ("comment", "코멘트"),
    "log.when": ("When", "시각"),
    "log.who": ("Who", "누가"),
    "log.what": ("What", "무엇을"),
    "log.messages": ("Messages from the game", "게임이 보낸 메시지"),
    "log.messages.hint": ("The last messages the game server received, newest first. A restart clears them.",
                          "게임 서버가 받은 최근 메시지를 최신 순으로 보여 줍니다. 서버를 다시 시작하면 지워집니다."),
    "log.messages.none": ("No message since the server started.", "서버가 시작한 뒤 받은 메시지가 없습니다."),
    "log.message": ("Message", "메시지"),
    "log.size": ("Bytes", "바이트"),
    "log.unhandled": ("no handler", "핸들러 없음"),
    "log.view.changes": ("Changes and messages", "변경 기록과 메시지"),
    "log.view.plays": ("Plays", "플레이"),
    "log.plays.player": ("Player", "플레이어"),
    "log.plays.everyone": ("Everyone", "모든 플레이어"),
    "log.plays.days": ("When", "기간"),
    "log.plays.days.all": ("Any time", "전체 기간"),
    "log.plays.days.1": ("Last 24 hours", "최근 24시간"),
    "log.plays.days.n": ("Last {n} days", "최근 {n}일"),
    "log.plays.word": ("Word in the song title", "곡 제목에 든 말"),
    "log.plays.show": ("Show", "보기"),
    "log.plays.csv": ("Download CSV", "CSV 다운로드"),
    "log.plays.none": ("No play matches.", "맞는 플레이가 없습니다."),
    "log.plays.newer": ("Newer", "최근"),
    "log.plays.older": ("Older", "이전"),
    "log.plays.page": ("Page {n}", "{n}쪽"),
    "backups.hint": ("A backup is made every day while the server runs; the newest {keep} of each kind stay.",
                     "서버가 실행되는 동안 하루에 한 번 백업하고 종류마다 최근 {keep}개를 남깁니다."),
    "backups.make": ("Back up now", "지금 백업"),
    "backups.made": ("Backed up: {name}", "백업했습니다: {name}"),
    "backups.none": ("No backup yet. The first is made when the server starts.", "아직 백업이 없습니다. 서버가 시작할 때 첫 백업을 만듭니다."),
    "backups.when": ("Made", "만든 때"),
    "backups.kind": ("Kind", "종류"),
    "backups.size": ("Size", "크기"),
    "backups.kind.daily": ("Daily", "자동"),
    "backups.kind.manual": ("By hand", "수동"),
    "backups.kind.restore": ("Before a restore", "복원 전"),
    "backups.kind.reset": ("Before a reset", "초기화 전"),
    "backups.kind.upload": ("Uploaded", "올린 백업"),
    "backups.download": ("Download", "다운로드"),
    "backups.upload": ("Upload a backup", "백업 올리기"),
    "backups.upload.file": ("Database file", "데이터베이스 파일"),
    "backups.upload.button": ("Upload", "올리기"),
    "backups.upload.hint": ("An openDMT3 database file of up to {mb} MB: a backup downloaded here or from another "
                            "server, or the openDMT3.sqlite of a stopped server.",
                            "openDMT3 데이터베이스 파일을 {mb} MB까지 올립니다. 여기나 다른 서버에서 받은 백업, 멈춘 서버의 openDMT3.sqlite입니다."),
    "backups.uploaded": ("Uploaded and checked: {name}", "올리고 검사했습니다: {name}"),
    "backups.restore": ("Restore", "복원"),
    "backups.restore.ask": ("Put the database back to {when}?", "{when} 시점으로 복원할까요?"),
    "backups.restore.detail": ("Accounts, plays and cards made or changed since then go. The database as it is now is "
                               "backed up first, so this can be undone.",
                               "그 뒤에 만들거나 바꾼 계정, 플레이, 카드가 사라집니다. 지금 상태를 먼저 백업하므로 복원 전으로 돌아갈 수 있습니다."),
    "backups.delete": ("Delete", "삭제"),
    "backups.delete.ask": ("Delete the backup of {when}?", "{when} 백업을 삭제할까요?"),
    "backups.delete.title": ("Delete backup", "백업 삭제"),
    "backups.delete.detail": ("Its file goes from the server, and this cannot be undone.",
                              "서버에서 그 파일이 지워지며 되돌릴 수 없습니다."),
    "backups.deleted": ("Deleted {name}.", "삭제했습니다: {name}"),
    "backups.restored": ("Restored {name}. The database as it was is backed up as {safety}.",
                         "{name} 시점으로 복원했습니다. 복원 전 상태는 백업해 두었습니다: {safety}"),
    "admin.make": ("Make an account", "계정 만들기"),
    "admin.made": ("Made {login_id}. Its password is shown this once: {password}",
                   "{login_id} 계정을 만들었습니다. 비밀번호는 지금 한 번만 보입니다: {password}"),
    "admin.message": ("Message to send", "보낼 메시지"),
    "admin.message.text": ("Your account on this openDMT3 server.\nAddress: {address}\nID: {login_id}\nPassword: "
                           "{password}\n\n1. Open the Download page and sign in with this ID and password: "
                           "{download}\n2. Download the launcher there and follow the page's steps.",
                           "openDMT3 서버 계정입니다.\n주소: {address}\nID: {login_id}\n비밀번호: {password}\n\n1. 다운로드 페이지를 열고 "
                           "이 ID와 비밀번호로 로그인하세요: {download}\n2. 그 페이지에서 런처를 다운로드하고 안내를 따르세요."),
    "admin.message.local": ("This message carries an address only this PC reaches ({address}). Before sending, put "
                            "this PC's address on the network in its place; ./dmt3 setup --address keeps it for the "
                            "next messages.",
                            "이 메시지에는 이 PC에서만 열리는 주소({address})가 들어 있습니다. 보내기 전에 이 PC의 네트워크 주소로 바꾸세요. ./dmt3 setup "
                            "--address로 정해 두면 다음 메시지부터 그 주소가 들어갑니다."),
    "admin.newpass": ("New password", "새 비밀번호"),
    "admin.newpass.ask": ("Give {login_id} a new password?", "{login_id}의 비밀번호를 새로 만들까요?"),
    "admin.newpass.detail": ("Their sign-ins end. The new password is shown once.",
                             "이 계정으로 로그인한 곳이 모두 로그아웃되고 새 비밀번호는 한 번만 보입니다."),
    "admin.rights.give": ("Give admin rights", "관리자 권한 주기"),
    "admin.rights.take": ("Take admin rights", "관리자 권한 빼기"),
    "admin.rights.given": ("{login_id} has admin rights now.", "{login_id}에게 관리자 권한을 주었습니다."),
    "admin.rights.taken": ("{login_id} has no admin rights now.", "{login_id}의 관리자 권한을 뺐습니다."),
    "admin.rename": ("Rename", "이름 바꾸기"),
    "admin.renamed": ("{login_id}'s DJ name is now {dj}.", "{login_id}의 DJ 이름을 바꿨습니다: {dj}"),
    "admin.newpass.done": ("New password for {login_id}, shown this once: {password}",
                           "{login_id}의 새 비밀번호입니다. 지금 한 번만 보입니다: {password}"),
    "admin.disable": ("Disable", "비활성화"),
    "admin.enable": ("Enable", "활성화"),
    "admin.reset": ("Reset plays", "기록 초기화"),
    "admin.reset.title": ("Reset plays", "플레이 기록 초기화"),
    "admin.reset.ask": ("Reset {login_id}'s plays?", "{login_id}의 플레이 기록을 초기화할까요?"),
    "admin.reset.detail": ("Their cleared stages leave the rankings, the songs' boards and their DJ page; the account, "
                           "its DJ card and its settings stay. The database is backed up first, so a restore brings "
                           "them back.",
                           "클리어한 스테이지가 랭킹, 곡 페이지, DJ 페이지에서 사라집니다. 계정과 DJ 카드, 설정은 그대로 "
                           "남습니다. 먼저 데이터베이스를 백업하므로 복원하면 되돌아옵니다."),
    "admin.reset.done": ("{login_id}'s plays are reset (cleared stages gone: {n}). The database as it was is backed "
                         "up as {backup}.",
                         "{login_id}의 플레이 기록을 초기화했습니다. 클리어한 스테이지 {n}개를 지웠습니다. 초기화 전 상태는 백업해 두었습니다: {backup}"),
    "admin.reset.all": ("Reset every play", "모든 플레이 기록 초기화"),
    "admin.reset.all.hint": ("Every player's cleared stages go, and the rankings, the songs' boards and the DJ pages "
                             "start again. Accounts, DJ cards and settings stay; the database is backed up first.",
                             "모든 플레이어의 클리어한 스테이지를 지우고 랭킹, 곡 페이지, DJ 페이지를 처음부터 다시 시작합니다. 계정과 DJ 카드, 설정은 그대로 남습니다. 먼저 "
                             "데이터베이스를 백업합니다."),
    "admin.reset.all.ask": ("Reset every player's plays?", "모든 플레이어의 플레이 기록을 초기화할까요?"),
    "admin.reset.all.detail": ("Every cleared stage leaves the rankings, the songs' boards and the DJ pages; accounts, "
                               "DJ cards and settings stay. The database is backed up first, so a restore brings "
                               "them back.",
                               "클리어한 스테이지가 모두 랭킹, 곡 페이지, DJ 페이지에서 사라집니다. 계정과 DJ 카드, "
                               "설정은 그대로 남습니다. 먼저 데이터베이스를 백업하므로 복원하면 되돌아옵니다."),
    "admin.reset.all.done": ("Every play is reset (cleared stages gone: {n}). The database as it was is backed up as "
                             "{backup}.",
                             "모든 플레이 기록을 초기화했습니다. 클리어한 스테이지 {n}개를 지웠습니다. 초기화 전 상태는 백업해 두었습니다: {backup}"),
    "admin.delete": ("Delete", "삭제"),
    "admin.delete.ask": ("Delete {login_id}?", "{login_id} 계정을 삭제할까요?"),
    "admin.delete.title": ("Delete player", "플레이어 삭제"),
    "admin.delete.detail": ("Their cleared stages go with them, and this cannot be undone.",
                            "클리어한 스테이지 기록도 함께 지워지며 되돌릴 수 없습니다."),
    "admin.sub": ("This server's players, cabinets, status, song list, logs and backups.",
                  "이 서버의 플레이어, 기체, 상태, 곡 목록, 로그, 백업입니다."),
    "common.cancel": ("Cancel", "취소"),
    "download.heading": ("Get the launcher", "런처 다운로드"),
    "admin.last": ("Last login", "마지막 로그인"),
    "admin.never": ("never", "없음"),
    "admin.role": ("Admin", "관리자"),
    "admin.disabled": ("Disabled", "비활성화됨"),
    "admin.cabinet.address": ("Address", "주소"),
    "admin.cabinet.client": ("Client", "클라이언트"),
    "admin.cabinet.player": ("Player", "플레이어"),
    "admin.cabinet.none": ("No cabinet is connected now.", "지금 접속 중인 기체가 없습니다."),
    "footer.licenses": ("Licenses", "라이선스"),
    "licenses.title": ("Licenses", "라이선스"),
    "licenses.sub": ("openDMT3's license, and the parts it is made with under theirs.",
                     "openDMT3의 라이선스와, 함께 쓰인 구성 요소의 라이선스입니다."),
    # openDMT3's own licence and what it does not cover, OpenDMTQ's Licenses page's two lines with openDMT3's names.
    "licenses.mit": ("MIT License", "MIT 라이선스"),
    "licenses.own": ("openDMT3's own code and guides are under the MIT License.",
                     "openDMT3 자체의 코드와 안내서는 MIT 라이선스를 따릅니다."),
    "licenses.game": ("It does not cover the game or its files (the client, songs, charts, pictures, videos, "
                      "sounds): they are not part of openDMT3, and it gives no right to use them.",
                      "게임과 게임 파일(클라이언트, 곡, 차트, 그림, 영상, 소리)에는 적용되지 않습니다. 이 파일들은 openDMT3의 일부가 아닙니다. 이 라이선스는 이 파일들을 쓸 "
                      "권리를 주지 않습니다."),
    # The parts the server and the launcher it hands out are made with (common.LICENCE_PARTS): a table of three
    # columns, what each is used for and its licence in the site's words (the parts' own names stay as they are).
    "licenses.parts": ("Third-party software", "서드파티 소프트웨어"),
    "licenses.th.part": ("Part", "구성 요소"),
    "licenses.th.use": ("Used for", "쓰이는 곳"),
    "licenses.th.licence": ("License", "라이선스"),
    "licenses.use.site": ("This site, its API and the launcher's", "이 사이트와 API, 런처의 API"),
    "licenses.use.libs": ("What those libraries bring along", "위 라이브러리가 함께 쓰는 라이브러리"),
    "licenses.use.pictures": ("The jackets and the DJ cards' pictures", "자켓과 DJ 카드 그림"),
    "licenses.use.python": ("The server and the launcher", "서버와 런처"),
    "licenses.use.7zip": ("Opening an archive that holds the game, on the server and in the launcher",
                          "게임이 든 압축 파일 열기(서버와 런처)"),
    "licenses.use.launcher": ("The launcher for Windows the Download page hands out: its window, its installer and "
                              "its updates", "다운로드 페이지가 주는 Windows용 런처의 창, 설치 파일, 업데이트"),
    "licenses.use.passes": ("The launcher's card reader library: the upscale filters and anti-aliasing in the game",
                            "런처의 카드 리더 라이브러리: 게임 화면의 확대 필터와 안티에일리어싱"),
    "licenses.use.runtime": ("Built into the card reader library by its compiler",
                             "컴파일러가 카드 리더 라이브러리에 넣는 런타임"),
    "licenses.use.mixer": ("The launcher's OpenAL Soft mixer for the game's sound, beside the card reader library",
                           "런처의 OpenAL Soft 믹서(게임 소리), 카드 리더 라이브러리 옆"),
    "licenses.use.system": ("The system the server's image runs on", "서버 이미지가 실행되는 시스템"),
    "licenses.use.fonts": ("The fonts of this site and of the launcher", "이 사이트와 런처의 글꼴"),
    "licenses.lic.site": ("BSD 3-Clause; python-multipart: Apache License 2.0",
                          "BSD 3-Clause, python-multipart는 Apache License 2.0"),
    "licenses.lic.libs": ("MIT (AnyIO, h11), BSD 3-Clause (idna, MarkupSafe, Click), PSF (typing_extensions), Apache "
                          "License 2.0 or BSD 2-Clause (packaging)",
                          "MIT(AnyIO, h11), BSD 3-Clause(idna, MarkupSafe, Click), PSF(typing_extensions), Apache "
                          "License 2.0 또는 BSD 2-Clause(packaging)"),
    "licenses.lic.pictures": ("MIT-CMU, with the licenses of the image libraries in it",
                              "MIT-CMU(안에 든 이미지 라이브러리의 라이선스 포함)"),
    "licenses.lic.python": ("PSF License; in its modules OpenSSL (Apache License 2.0), SQLite (public domain), libffi "
                            "and Expat (MIT), zlib (zlib License), mpdecimal and bzip2 (BSD-style), liblzma (0BSD)",
                            "PSF 라이선스. 모듈 안의 OpenSSL(Apache License 2.0), SQLite(퍼블릭 도메인), libffi와 "
                            "Expat(MIT), zlib(zlib 라이선스), mpdecimal과 bzip2(BSD 계열), liblzma(0BSD)"),
    "licenses.lic.7zip": ("GNU LGPL, with the unRAR license restriction and BSD licenses for some code",
                          "GNU LGPL(일부 코드는 unRAR 라이선스 제한과 BSD 라이선스)"),
    "licenses.lic.launcher": ("Tcl/Tk license (BSD-style), MIT (Velopack), GPL 2 with the Bootloader Exception "
                              "(PyInstaller)", "Tcl/Tk 라이선스(BSD 계열), MIT(Velopack), GPL 2와 Bootloader "
                              "Exception(PyInstaller)"),
    "licenses.lic.passes": ("MIT (FSR 1, NIS, SMAA), NVIDIA's notice (FXAA 3.11)",
                            "MIT(FSR 1, NIS, SMAA), NVIDIA의 고지(FXAA 3.11)"),
    "licenses.lic.runtime": ("ZPL 2.1 and other permissive licenses (mingw-w64), GPL 3 with the GCC Runtime Library "
                             "Exception (GCC)", "ZPL 2.1과 그 밖의 허용 라이선스(mingw-w64), GPL 3와 GCC Runtime "
                             "Library Exception(GCC)"),
    "licenses.lic.mixer": ("GNU LGPL 2.1 or later (DSOAL), GNU LGPL 2 or later (OpenAL Soft), with BSD 3-Clause, "
                           "PFFFT's and MIT licenses for some code; each release carries their source",
                           "GNU LGPL 2.1 이상(DSOAL), GNU LGPL 2 이상(OpenAL Soft), 일부 코드는 BSD 3-Clause, PFFFT, "
                           "MIT 라이선스. 릴리스마다 원천을 함께 둠"),
    "licenses.lic.system": ("Each its own: GPL, LGPL, BSD, MIT and others", "패키지마다 다름: GPL, LGPL, BSD, MIT 등"),
    "licenses.lic.fonts": ("SIL Open Font License 1.1", "SIL Open Font License 1.1"),
    "licenses.texts": ("The launcher carries every full text in its program's licenses folder, with NOTICES.txt "
                       "saying which is whose, and the card reader library's notices beside the library. The "
                       "server's image keeps each text with its part: the Python packages' in their folders, 7-Zip's "
                       "in /usr/local/share/doc/7-zip, the system's in /usr/share/doc.",
                       "런처는 모든 전문을 프로그램의 licenses 폴더에 담고 어느 것이 무엇의 것인지 NOTICES.txt에 적어 둡니다. 카드 리더 라이브러리의 고지는 라이브러리 "
                       "옆에 있습니다. 서버 이미지는 각 전문을 구성 요소 곁에 둡니다(파이썬 패키지는 각자의 폴더, 7-Zip은 /usr/local/share/doc/7-zip, 시스템 "
                       "패키지는 /usr/share/doc)."),
    "licenses.ofl": ("SIL Open Font License 1.1", "SIL Open Font License 1.1"),
    "licenses.wide": ("DMT3 Wide, the titles' face: made from Saira at its widest and boldest, Latin letters only.",
                      "DMT3 Wide(제목 글꼴): Saira를 가장 넓고 굵게, 라틴 문자만 남겨 만들었습니다."),
    "licenses.text": ("DMT3 Text, the text face: made from Pretendard 1.3.9, cut to the Hangul of KS X 1001 and Latin.",
                      "DMT3 Text(본문 글꼴): Pretendard 1.3.9에서 KS X 1001 한글과 라틴 문자만 남겨 만들었습니다."),
    "licenses.pretendard": ("Pretendard, the launcher's text face, as it is (served at /fonts/ with the launcher's "
                            "wide face).",
                            "Pretendard(런처 본문 글꼴): 바꾸지 않은 그대로입니다(런처의 제목 글꼴과 함께 /fonts/에 있음)."),
    "licenses.show": ("The license in full", "라이선스 전문"),
    # The footer's two lines, OpenDMTQ's word for word with openDMT3's names (the second is the one place the words
    # "game data" are said: the software holds none).
    "footer.notice": ("An unofficial, non-commercial project, not affiliated with or endorsed by NEOWIZ. DJMAX and "
                      "TECHNIKA belong to NEOWIZ.",
                      "NEOWIZ와 관계없고 승인받지 않은 비공식 비상업 프로젝트입니다. DJMAX와 TECHNIKA의 권리는 NEOWIZ에 "
                      "있습니다."),
    "footer.rights": ("openDMT3's software contains no game data; please use it only with game files you have the right "
                      "to use. If a rights holder asks, the project will be made private or taken down.",
                      "openDMT3 소프트웨어에는 게임 데이터가 들어 있지 않습니다. 쓸 권리가 있는 게임 파일로만 써 주세요. "
                      "권리자가 요청하면 프로젝트를 비공개로 돌리거나 내립니다."),
    "me.title": ("My account", "내 계정"),
    "me.sub": ("Your DJ card, your DJ name, your password and your API tokens.",
               "DJ 카드, DJ 이름, 비밀번호를 바꾸고 API 토큰을 만듭니다."),
    "me.card": ("DJ card", "DJ 카드"),
    "me.card.comment": ("Comment", "코멘트"),
    "me.card.icon": ("Icon", "아이콘"),
    "me.card.plate": ("Plate", "플레이트"),
    "me.card.pattern": ("Plate pattern", "플레이트 패턴"),
    "me.card.count": ("{n} to choose from", "{n}개 중에서"),
    "me.card.number": ("No. {n}", "{n}번"),
    "me.card.save": ("Save the card", "카드 저장"),
    "me.card.hint": ("The game shows your card from your next login. The comment is up to {max} characters.",
                     "다음 로그인부터 게임에 이 카드가 보입니다. 코멘트는 {max}자까지 씁니다."),
    "me.card.no_pictures": ("The icons and plates to choose from show once the server's owner imports the song list. "
                            "The comment can be set now.",
                            "고를 아이콘과 플레이트는 서버 운영자가 곡 목록을 가져오면 나옵니다. 코멘트는 지금도 정할 수 있습니다."),
    "me.card.done": ("Your DJ card is saved. The game shows it from your next login.",
                     "DJ 카드를 저장했습니다. 다음 로그인부터 게임에 보입니다."),
    "me.dj.new": ("New name", "새 이름"),
    "me.dj.save": ("Change the name", "이름 바꾸기"),
    "me.dj.hint": ("Shown on your DJ card in the game and on this site, up to {max} characters.",
                   "게임의 DJ 카드와 이 사이트에 나옵니다. {max}자까지 씁니다."),
    "me.dj_name.done": ("Your DJ name is changed. The game shows it from your next login.",
                        "DJ 이름을 바꿨습니다. 게임에는 다음 로그인부터 나옵니다."),
    "me.password": ("Password", "비밀번호"),
    "me.password.current": ("Current password", "지금 비밀번호"),
    "me.password.new": ("New password", "새 비밀번호"),
    "me.password.again": ("New password again", "새 비밀번호 확인"),
    "me.password.save": ("Change the password", "비밀번호 바꾸기"),
    "me.password.hint": ("{min} to {max} letters or digits. After a change, sign in again in the launcher.",
                         "영문자와 숫자 {min}~{max}자입니다. 바꾼 뒤에는 런처에서 다시 로그인하세요."),
    "me.password.done": ("Your password is changed, and your card with it.", "비밀번호를 바꿨습니다. 카드도 함께 바뀌었습니다."),
    "me.password.wrong": ("The current password is not right.", "지금 비밀번호가 맞지 않습니다."),
    "me.password.mismatch": ("The two new passwords are not the same.", "새 비밀번호 두 개가 서로 다릅니다."),
    "me.tokens": ("API tokens", "API 토큰"),
    "me.tokens.name": ("Name", "이름"),
    "me.tokens.scope": ("Scope", "권한"),
    "me.tokens.read": ("Read only", "읽기만"),
    "me.tokens.write": ("Read and write", "읽기와 쓰기"),
    "me.tokens.make": ("Make a token", "토큰 만들기"),
    "me.tokens.made": ("The token {name}, shown this once:", "{name} 토큰입니다. 지금 한 번만 보입니다:"),
    "me.tokens.none": ("No token yet.", "아직 토큰이 없습니다."),
    "me.tokens.created": ("Made", "만든 때"),
    "me.tokens.used": ("Last used", "마지막 사용"),
    "me.tokens.never": ("never", "없음"),
    "me.tokens.revoke": ("Revoke", "폐기"),
    "me.tokens.revoke.title": ("Revoke token", "토큰 폐기"),
    "me.tokens.revoke.ask": ("Revoke the token {name}?", "{name} 토큰을 폐기할까요?"),
    "me.tokens.revoke.detail": ("A program that uses it can no longer use the API with it, and this cannot be undone.",
                                "이 토큰을 쓰는 프로그램은 더는 이 토큰으로 API를 쓸 수 없으며 되돌릴 수 없습니다."),
    "me.tokens.revoked": ("The token {name} is revoked.", "{name} 토큰을 폐기했습니다."),
    "me.tokens.hint": ("A program of yours uses the API with a token (Authorization: Bearer and the token). A "
                       "read-only token makes GET calls, none of an admin's. A new password revokes every token; an "
                       "account holds {most} at most.",
                       "내 프로그램이 토큰으로 API를 씁니다(Authorization: Bearer와 토큰). 읽기만 하는 토큰은 관리자의 호출을 뺀 GET 호출만 합니다. 비밀번호를 "
                       "바꾸면 모든 토큰이 폐기됩니다. 계정마다 {most}개까지 둘 수 있습니다."),
    "error.title": ("Page not found", "페이지를 찾을 수 없습니다"),
    "error.text": ("There is nothing at this address.", "이 주소에는 아무것도 없습니다."),
    "error.home": ("Home", "홈으로"),
    "error.unavailable.title": ("Not available right now", "지금은 볼 수 없습니다"),
    "error.unavailable.text": ("This page cannot be shown right now. Try again in a while.",
                               "지금은 이 페이지를 보여 줄 수 없습니다. 잠시 뒤에 다시 시도하세요."),
    "error.busy.title": ("Too many requests", "요청이 너무 많습니다"),
    "error.busy.text": ("Try again in {seconds} seconds.", "{seconds}초 뒤에 다시 시도하세요."),
    "error.busy.text.one": ("Try again in 1 second.", "1초 뒤에 다시 시도하세요."),
    "title.home": ("Home", "홈"),
    "title.rankings": ("Rankings", "랭킹"),
    "title.songs": ("Songs", "곡"),
    "form.expired": ("The form expired; try again.", "페이지가 오래되었습니다. 다시 시도해 주세요."),
}


def words(language):
    """A function key -> text in the language (Korean entries fall back to English when missing).

    Its .error(e) gives what a raised error says in the same language (errors.py).
    """
    korean = language == "ko"

    def look(key, **kw):
        en, ko = TEXT.get(key, (key, key))
        text = ko if korean and ko else en
        return text.format(**kw) if kw else text

    look.error = lambda error: errors.say(error, "ko" if korean else "en")
    return look


# The change log's lines (Admin, Logs): the server keeps each as the English line its code writes ("started
# maintenance"), which the API gives as it is; the page words it in the reader's language when it shows it. Each line's
# shape is its English entry above (log.change.*), with {0}, {1}... where its values stand, tried in this order (a
# cabinet's naming before an account's, which it would also fit).
CHANGES = ("log.change.cabinet.named", "log.change.account.made", "log.change.account.password",
           "log.change.account.named", "log.change.account.card", "log.change.account.admin_on",
           "log.change.account.admin_off", "log.change.account.disabled", "log.change.account.enabled",
           "log.change.account.deleted", "log.change.notice.set", "log.change.notice.cleared",
           "log.change.maintenance.on", "log.change.maintenance.off", "log.change.backup.deleted",
           "log.change.reset.one", "log.change.reset.all", "log.change.token.made", "log.change.token.revoked",
           "log.change.backup.made", "log.change.backup.restored", "log.change.backup.uploaded", "log.change.songlist")


def _shape(english):
    """A change line's English shape as a pattern: its words as they are, each {n} a group (the last takes the rest
    of the line, the others as little as fits)."""
    last = max(int(n) for n in re.findall(r"\{(\d)\}", english)) if "{" in english else -1
    parts = re.split(r"\{(\d)\}", english)
    # Words and gaps alternate: the words escaped, each gap a named group.
    pattern = "".join(re.escape(part) if i % 2 == 0 else "(?P<v%s>%s)" % (part, ".*" if int(part) == last else ".+?")
                      for i, part in enumerate(parts))
    return re.compile("^%s$" % pattern, re.S)


# Each shape made once, when the site starts.
_SHAPES = [(key, _shape(TEXT[key][0])) for key in CHANGES]


def _part(korean, text):
    """A value that is words of the server's own (a card's part, what an import missed), in the reader's language;
    anything else (an ID, a name, a file) as it is."""
    pair = TEXT.get("log.change.part." + text)
    return pair[1] if pair and korean else text


def changed(language, what):
    """A line of the change log in the reader's language: worded from its shape when it is one the server writes,
    else as it was kept (a line from a newer or an older openDMT3)."""
    if language != "ko":
        # The line is kept in English.
        return what
    for key, shape in _SHAPES:
        found = shape.match(what)
        if not found:
            continue
        values = [found.group("v%d" % n) for n in range(len(found.groupdict()))]
        if key == "log.change.account.card":
            # The card's parts changed, by their names on the Account page.
            values[1] = ", ".join(_part(True, name) for name in values[1].split(", "))
        elif key == "log.change.songlist":
            # Where it came from when that is an upload, and each part it missed.
            upload = _shape(TEXT["log.change.songlist.uploaded"][0]).match(values[0])
            if upload:
                values[0] = TEXT["log.change.songlist.uploaded"][1].format(upload.group("v0"))
            values[2] = ", ".join(_part(True, part) for part in values[2].split(", "))
        return TEXT[key][1].format(*values)
    return what
