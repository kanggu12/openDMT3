"""The site's words for the account area and the admin's page of one player, in English and Korean (strings.py takes
them into its table): kept apart so the pages' own words stay together.
"""

TEXT = {
    # Signing in to a banned account, and after deleting one's own.
    "signin.banned": ("This account is banned: {reason}", "이용이 정지된 계정입니다. 사유: {reason}"),
    "signin.gone": ("Your account is deleted.", "계정을 삭제했습니다."),
    # The account area: three sections.
    "me.sub": ("Your profile and DJ card, your account, and how you sign in.",
               "프로필과 DJ 카드, 계정 정보, 로그인과 보안을 관리합니다."),
    "me.sections": ("Sections of your account", "내 계정의 구역"),
    "me.section.profile": ("Profile", "프로필"),
    "me.section.account": ("Account", "계정"),
    "me.section.security": ("Security", "보안"),
    "dj.edit": ("Edit my profile", "내 프로필 꾸미기"),
    "me.profile.public": ("See your page as others see it", "다른 사람에게 보이는 내 페이지 보기"),
    # What the game shows of a DJ besides the card.
    "profile.level": ("Level", "레벨"),
    "profile.exp": ("Experience", "경험치"),
    "profile.points": ("MAX points", "MAX 포인트"),
    "profile.points.short": ("MAX", "MAX"),
    # The picture: the site's own.
    "me.picture": ("Picture", "프로필 사진"),
    "me.picture.file": ("A picture", "사진 파일"),
    "me.picture.rules": ("PNG, JPEG, WebP or GIF, up to {mb} MB. It is cut to a square of {size} pixels from its "
                         "middle. Shown on this site; the game shows your DJ icon.",
                         "PNG, JPEG, WebP, GIF 파일을 {mb}MB까지 올릴 수 있습니다. 가운데를 {size}픽셀 정사각형으로 "
                         "잘라 씁니다. 이 사이트에 보이고, 게임에는 DJ 아이콘이 보입니다."),
    "me.picture.upload": ("Upload", "올리기"),
    "me.picture.clear": ("Remove the picture", "사진 지우기"),
    "me.picture.clear.ask": ("Remove your picture?", "프로필 사진을 지울까요?"),
    "me.picture.none": ("This server cannot take pictures right now.", "이 서버는 지금 사진을 받을 수 없습니다."),
    "me.picture.size": ("A picture is up to {mb} MB.", "사진은 {mb}MB까지 올릴 수 있습니다."),
    "me.picture.kind": ("That file is not a picture. Upload a PNG, JPEG, WebP or GIF.",
                        "사진 파일이 아닙니다. PNG, JPEG, WebP, GIF 파일을 올려 주세요."),
    "me.picture.pixels": ("That picture has too many pixels. Upload one of up to 4096 × 4096.",
                          "사진의 픽셀이 너무 많습니다. 4096 × 4096 이하로 올려 주세요."),
    "me.picture.done": ("Your picture is saved.", "프로필 사진을 저장했습니다."),
    "me.picture_clear.done": ("Your picture is removed.", "프로필 사진을 지웠습니다."),
    # The account section.
    "me.account.facts": ("This account", "계정 정보"),
    "me.account.since": ("Made", "만든 날"),
    "me.account.kind": ("Kind", "종류"),
    "me.account.player": ("Player", "플레이어"),
    "me.account.id_hint": ("The ID signs you in here and in the launcher, and stays the same.",
                           "ID로 이 사이트와 런처에 로그인합니다. 계정의 ID는 바꿀 수 없습니다."),
    # The security section.
    "me.password.show": ("Show", "보기"),
    "me.password.hide": ("Hide", "숨기기"),
    "me.signins": ("Sign-ins", "로그인"),
    "me.signins.hint": ("Signs out every other browser signed in to this account. This one stays signed in, and so "
                        "does the launcher (a new password signs it out).",
                        "이 계정으로 로그인한 다른 브라우저를 모두 로그아웃합니다. 지금 브라우저와 런처는 그대로입니다"
                        "(런처는 비밀번호를 바꾸면 로그아웃됩니다)."),
    "me.signins.out": ("Sign out everywhere else", "다른 곳 모두 로그아웃"),
    "me.signins.ask": ("Sign out every other browser?", "다른 브라우저를 모두 로그아웃할까요?"),
    "me.signins.detail": ("They need the password to sign in again.", "다시 로그인하려면 비밀번호가 필요합니다."),
    "me.signout_others.done": ("Every other browser is signed out.", "다른 브라우저를 모두 로그아웃했습니다."),
    "me.delete": ("Delete the account", "계정 삭제"),
    "me.delete.hint": ("Your plays, DJ card and picture go with it, and the card stops logging in. Type your password "
                       "to delete it.",
                       "플레이 기록, DJ 카드, 프로필 사진이 함께 지워지고 카드로 로그인할 수 없게 됩니다. 지우려면 "
                       "비밀번호를 입력하세요."),
    "me.delete.ask": ("Delete your account?", "계정을 삭제할까요?"),
    "me.delete.detail": ("This cannot be undone.", "되돌릴 수 없습니다."),
    "me.delete.yes": ("Delete my account", "내 계정 삭제"),
    "me.delete.last_admin": ("You are the server's only admin: give another account admin rights first.",
                             "이 서버의 유일한 관리자입니다. 다른 계정에 관리자 권한을 먼저 주세요."),
    # The admin's page of one player.
    "player.sub": ("Their state in the game and on this site, and every change to it.",
                   "게임과 사이트에서의 상태와 그 변경을 한 곳에서 관리합니다."),
    "player.back": ("← Every player", "← 플레이어 목록"),
    "player.banned": ("Banned", "이용 정지"),
    "player.card": ("Card", "카드"),
    "player.next_login": ("The game shows each change from the player's next card login.",
                          "게임에는 플레이어가 다음에 카드로 로그인할 때부터 반영됩니다."),
    "player.dj_page": ("DJ page", "DJ 페이지"),
    "player.plays_log": ("Their plays", "플레이 기록"),
    "player.points.unlimited": ("Unlimited", "무제한"),
    "player.points.hint": ("The game's currency, earned by playing and shown beside the DJ name on the song select. "
                           "A balance is 0 to {most}.",
                           "게임의 재화입니다. 플레이로 쌓이고 곡 선택 화면의 DJ 이름 옆에 보입니다. 0~{most}까지 "
                           "가질 수 있습니다."),
    "player.points.unlimited.switch": ("Unlimited MAX points", "MAX 포인트 무제한"),
    "player.points.add": ("Add or take (below 0)", "더하기 또는 빼기(음수)"),
    "player.points.add.button": ("Add", "더하기"),
    "player.points.set": ("Set the balance", "잔액 정하기"),
    "player.points.set.button": ("Set", "정하기"),
    "player.level.plays": ("From the stages cleared: {plays} experience.", "클리어한 스테이지로 얻은 경험치 {plays}."),
    "player.level.from": ("From the stages cleared: {plays} experience, with {extra} set by an admin.",
                          "클리어한 스테이지로 얻은 경험치 {plays}, 관리자가 더한 {extra}."),
    "player.level.set": ("Set the level", "레벨 정하기"),
    "player.level.set.button": ("Set", "정하기"),
    "player.level.clear": ("Back to the level of their plays", "플레이로 얻은 레벨로 되돌리기"),
    "player.level.no_table": ("The levels show once the server's owner imports the song list.",
                              "서버 운영자가 곡 목록을 가져오면 레벨을 정할 수 있습니다."),
    "player.ban": ("Ban", "이용 정지"),
    "player.ban.hint": ("A banned player cannot log in at the cabinet, on this site or in the launcher, and is told the "
                        "reason when they sign in. Up to {max} characters.",
                        "정지된 플레이어는 게임, 이 사이트, 런처에 로그인할 수 없고, 로그인할 때 사유를 봅니다. "
                        "사유는 {max}자까지입니다."),
    "player.ban.reason": ("Reason", "사유"),
    "player.ban.yes": ("Ban", "정지하기"),
    "player.ban.ask": ("Ban {login_id}?", "{login_id}의 이용을 정지할까요?"),
    "player.ban.detail": ("Their card stops logging in and their sign-ins end at once, and they leave the rankings until "
                          "the ban is lifted.",
                          "카드 로그인이 바로 막히고 이 계정으로 로그인한 곳이 모두 로그아웃되며, 정지를 풀 때까지 순위에서 "
                          "빠집니다."),
    "player.ban.on": ("The game refuses their card, and the site and the launcher their sign-in.",
                      "게임은 카드를, 사이트와 런처는 로그인을 거부합니다."),
    "player.unban": ("Lift the ban", "정지 풀기"),
    "player.disabled.hint": ("The account is disabled without a reason.", "사유 없이 비활성화된 계정입니다."),
    "player.newpass.hint": ("Shown once, with the message to send.", "한 번만 보이며 보낼 메시지가 함께 나옵니다."),
    "player.picture.clear.ask": ("Remove {login_id}'s picture?", "{login_id}의 프로필 사진을 지울까요?"),
    "player.history": ("Changes", "변경 기록"),
    "player.history.none": ("No change yet.", "아직 변경이 없습니다."),
    "player.done.points": ("MAX points: {n} now.", "MAX 포인트가 이제 {n}입니다."),
    "player.done.unlimited_on": ("Unlimited MAX points are on.", "MAX 포인트 무제한을 켰습니다."),
    "player.done.unlimited_off": ("Unlimited MAX points are off.", "MAX 포인트 무제한을 껐습니다."),
    "player.done.level": ("The level is {n} now.", "레벨이 이제 {n}입니다."),
    "player.done.level_clear": ("The level is the one of their plays again.", "플레이로 얻은 레벨로 되돌렸습니다."),
    "player.done.ban": ("Banned: {reason}", "이용을 정지했습니다. 사유: {reason}"),
    "player.done.unban": ("The ban is lifted.", "이용 정지를 풀었습니다."),
    "player.done.card": ("The DJ card is saved.", "DJ 카드를 저장했습니다."),
    "player.done.picture_clear": ("The picture is removed.", "프로필 사진을 지웠습니다."),
    "player.done.disable": ("The account is disabled.", "계정을 비활성화했습니다."),
    "player.done.enable": ("The account is enabled.", "계정을 활성화했습니다."),
    # The change log's lines of these changes (strings.CHANGES words them for a Korean reader).
    "log.change.player.points.set": ("set the MAX points of {0} to {1}", "{0}의 MAX 포인트를 {1}(으)로 정함"),
    "log.change.player.points.gave": ("gave {0} MAX points to {1}", "{1}에게 MAX 포인트 {0} 더함"),
    "log.change.player.points.took": ("took {0} MAX points from {1}", "{1}의 MAX 포인트 {0} 뺌"),
    "log.change.player.unlimited.on": ("turned unlimited MAX points on for {0}", "{0}의 MAX 포인트 무제한 켬"),
    "log.change.player.unlimited.off": ("turned unlimited MAX points off for {0}", "{0}의 MAX 포인트 무제한 끔"),
    "log.change.player.level": ("set the level of {0} to {1}", "{0}의 레벨을 {1}(으)로 정함"),
    "log.change.player.level.clear": ("gave {0} the level of their plays again", "{0}의 레벨을 플레이로 얻은 레벨로 되돌림"),
    "log.change.player.banned": ("banned {0}: {1}", "{0} 이용 정지: {1}"),
    "log.change.player.picture": ("changed the picture of {0}", "{0}의 프로필 사진을 바꿈"),
    "log.change.player.picture.clear": ("removed the picture of {0}", "{0}의 프로필 사진을 지움"),
    "log.change.player.signout": ("signed {0} out everywhere else", "{0}의 다른 로그인을 모두 끝냄"),
}

# The change log's lines above, in the order they are tried (strings.changed).
CHANGES = ("log.change.player.points.set", "log.change.player.points.gave", "log.change.player.points.took",
           "log.change.player.unlimited.on", "log.change.player.unlimited.off", "log.change.player.level",
           "log.change.player.level.clear", "log.change.player.banned", "log.change.player.picture",
           "log.change.player.picture.clear", "log.change.player.signout")
