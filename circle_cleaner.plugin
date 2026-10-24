"""
Circle Cleaner Plugin for exteraGram / AyuGram (Android)
Удаление видеосообщений (кружков) через кнопку Plugins в чате или текстовой командой.
"""

import threading
import time
from typing import Any, Dict, List

from base_plugin import BasePlugin, HookResult, HookStrategy, MenuItemData, MenuItemType
from client_utils import get_last_fragment, get_messages_controller, send_request
from org.telegram.messenger import MessagesController, UserConfig
from org.telegram.tgnet import ConnectionsManager, TLRPC
from ui.bulletin import BulletinHelper
from ui.settings import Divider, Header, Switch, Text

try:
    from client_utils import RequestCallback
except Exception:
    RequestCallback = None

try:
    from ui.alert import AlertDialogBuilder
except Exception:
    AlertDialogBuilder = None

try:
    from android_utils import run_on_ui_thread
except Exception:
    def run_on_ui_thread(fn):
        fn()

try:
    from org.telegram.ui import LaunchActivity
except Exception:
    LaunchActivity = None


__id__ = "circle_cleaner"
__name__ = "Circle Cleaner"
__description__ = "Удаление видеосообщений (кружков) из чата через кнопку меню Plugins или команду"
__author__ = "VANTA"
__version__ = "1.4.1"
__icon__ = "exteraPlugins/1"
__min_version__ = "11.0.0"
__permissions__ = ["network"]


class CircleCleanerPlugin(BasePlugin):
    def on_plugin_load(self):
        self.add_on_send_message_hook()

        # 1. Меню действий чата (3 точки вверху чата -> Plugins -> Удалить кружочки)
        try:
            self.add_menu_item(
                MenuItemData(
                    menu_type=MenuItemType.CHAT_ACTION_MENU,
                    text="Удалить кружочки",
                    icon="msg_delete",
                    priority=100,
                    item_id="circle_cleaner_chat_action",
                    on_click=self.on_chat_menu_click,
                )
            )
        except Exception as e:
            self.logger.warning(f"Could not register CHAT_ACTION_MENU: {e}")

        # 2. Контекстное меню сообщения (зажатие или клик по любому сообщению в чате)
        try:
            self.add_menu_item(
                MenuItemData(
                    menu_type=MenuItemType.MESSAGE_CONTEXT_MENU,
                    text="Удалить кружки в чате",
                    icon="msg_delete",
                    priority=100,
                    item_id="circle_cleaner_msg_ctx",
                    on_click=self.on_chat_menu_click,
                )
            )
        except Exception as e:
            self.logger.warning(f"Could not register MESSAGE_CONTEXT_MENU: {e}")

        # 3. Меню профиля чата (3 точки в профиле собеседника / группы)
        try:
            self.add_menu_item(
                MenuItemData(
                    menu_type=MenuItemType.PROFILE_ACTION_MENU,
                    text="Удалить кружочки",
                    icon="msg_delete",
                    priority=100,
                    item_id="circle_cleaner_profile",
                    on_click=self.on_chat_menu_click,
                )
            )
        except Exception as e:
            self.logger.warning(f"Could not register PROFILE_ACTION_MENU: {e}")

        # 4. Главное меню (3 точки на главном экране списка чатов)
        try:
            self.add_menu_item(
                MenuItemData(
                    menu_type=MenuItemType.MAIN_MENU,
                    text="Circle Cleaner",
                    icon="msg_delete",
                    priority=100,
                    item_id="circle_cleaner_main",
                    on_click=self.on_chat_menu_click,
                )
            )
        except Exception as e:
            self.logger.warning(f"Could not register MAIN_MENU: {e}")

        # 5. Боковое меню (шторка / Navigation Drawer)
        try:
            self.add_menu_item(
                MenuItemData(
                    menu_type=MenuItemType.DRAWER_MENU,
                    text="Circle Cleaner",
                    icon="msg_delete",
                    priority=100,
                    item_id="circle_cleaner_drawer",
                    on_click=self.on_chat_menu_click,
                )
            )
        except Exception as e:
            self.logger.warning(f"Could not register DRAWER_MENU: {e}")

        self._is_running = False
        self._cancel_requested = False
        self._progress_builder = None
        self.logger.info("Circle Cleaner v1.4.1 loaded successfully!")

    def on_plugin_unload(self):
        self._cancel_requested = True
        self._is_running = False
        self._dismiss_progress()
        self.logger.info("Circle Cleaner unloaded.")

    def create_settings(self) -> List[Any]:
        return [
            Header(text="Настройки Circle Cleaner"),
            Switch(
                key="only_my",
                text="Удалять только свои кружки по умолчанию",
                subtext="Если включено, по умолчанию удаляются только ваши кружочки",
                default=False,
            ),
            Switch(
                key="revoke",
                text="Удалять для всех участников (Revoke)",
                subtext="Удалять кружки у обоих собеседников в личных чатах и группах",
                default=True,
            ),
            Divider(),
            Header(text="Как использовать"),
            Text(
                text="В чате через кнопку Plugins",
                subtext="Нажмите 3 точки вверху чата -> Plugins -> 'Удалить кружочки', либо зажмите любое сообщение в чате",
            ),
            Text(
                text="Текстовая команда",
                subtext=".delcircles [all | my] [число]\n.delcircles stop - остановить удаление",
            ),
        ]

    def on_chat_menu_click(self, context: Dict[str, Any]):
        """Обработчик нажатия на кнопку меню Plugins"""
        account = context.get("account")
        if account is None:
            account = getattr(UserConfig, "selectedAccount", 0)

        # 1. Извлечение объектов Chat / User напрямую из context
        raw_chat = context.get("chat")
        raw_user = context.get("user")
        raw_msg = context.get("message")
        fragment = context.get("fragment") or get_last_fragment()

        if not raw_chat and not raw_user and fragment:
            try:
                if hasattr(fragment, "getCurrentChat"):
                    raw_chat = fragment.getCurrentChat()
                if hasattr(fragment, "getCurrentUser"):
                    raw_user = fragment.getCurrentUser()
            except Exception:
                pass

        # 2. Определение dialog_id
        dialog_id = (
            context.get("dialog_id")
            or context.get("chatId")
            or context.get("userId")
        )
        if dialog_id is None and raw_msg:
            dialog_id = getattr(raw_msg, "dialog_id", None)

        if dialog_id is None and fragment and hasattr(fragment, "getDialogId"):
            try:
                dialog_id = fragment.getDialogId()
            except Exception:
                pass

        if dialog_id is None:
            if raw_chat:
                cid = getattr(raw_chat, "id", None)
                if cid is not None:
                    try:
                        from org.telegram.messenger import ChatObject
                        is_c = ChatObject.isChannel(raw_chat)
                    except Exception:
                        is_c = getattr(raw_chat, "broadcast", False) or getattr(raw_chat, "megagroup", False)
                    dialog_id = (-1000000000000 - cid) if is_c else -cid
            elif raw_user:
                dialog_id = getattr(raw_user, "id", None)

        if dialog_id is None and not raw_chat and not raw_user:
            BulletinHelper.show_info("ℹ️ Откройте чат и выберите 'Удалить кружочки' в меню (3 точки) или зажмите любое сообщение.")
            return

        activity = (
            context.get("context")
            or (fragment.getParentActivity() if fragment else None)
            or getattr(LaunchActivity, "instance", None)
        )

        # Если уже выполняется - показываем диалог остановки
        if self._is_running:
            def show_stop_dialog():
                if not activity or not AlertDialogBuilder:
                    self._cancel_requested = True
                    BulletinHelper.show_info("Остановка процесса удаления...")
                    return

                try:
                    builder = AlertDialogBuilder(activity)
                    builder.set_title("Circle Cleaner")
                    builder.set_message("Процесс удаления кружков уже выполняется.")
                    builder.set_positive_button(
                        "Остановить",
                        lambda bld, which: (bld.dismiss(), self._request_stop())
                    )
                    builder.set_negative_button("Закрыть", lambda bld, which: bld.dismiss())
                    builder.show()
                except Exception as e:
                    self.logger.error(f"Error showing stop dialog: {e}")
                    self._request_stop()

            run_on_ui_thread(show_stop_dialog)
            return

        # Показываем всплывающий диалог выбора режима удаления
        def show_picker_dialog():
            if not activity or not AlertDialogBuilder:
                default_only_my = self.get_setting("only_my", False)
                self._start_cleaning(
                    activity, account, dialog_id, only_my=default_only_my, limit=0,
                    raw_chat=raw_chat, raw_user=raw_user
                )
                return

            try:
                builder = AlertDialogBuilder(activity)
                builder.set_title("Удаление кружочков")
                builder.set_message("Какие видеосообщения (кружки) удалить из этого чата?")

                builder.set_positive_button(
                    "Все кружки",
                    lambda bld, which: (
                        bld.dismiss(),
                        self._start_cleaning(
                            activity, account, dialog_id, only_my=False, limit=0,
                            raw_chat=raw_chat, raw_user=raw_user
                        )
                    )
                )
                builder.set_negative_button(
                    "Только мои",
                    lambda bld, which: (
                        bld.dismiss(),
                        self._start_cleaning(
                            activity, account, dialog_id, only_my=True, limit=0,
                            raw_chat=raw_chat, raw_user=raw_user
                        )
                    )
                )
                builder.set_neutral_button("Отмена", lambda bld, which: bld.dismiss())
                builder.show()
            except Exception as e:
                self.logger.error(f"Error showing picker dialog: {e}")
                default_only_my = self.get_setting("only_my", False)
                self._start_cleaning(
                    activity, account, dialog_id, only_my=default_only_my, limit=0,
                    raw_chat=raw_chat, raw_user=raw_user
                )

        run_on_ui_thread(show_picker_dialog)

    def on_send_message_hook(self, account: int, params: Any) -> HookResult:
        """Резервный перехват текстовых команд в чате"""
        text = getattr(params, "message", None)
        if not isinstance(text, str):
            return HookResult()

        text_stripped = text.strip()
        cmd_prefixes = (".delcircles", ".delround", ".rmcircles", ".кружки")
        matched_prefix = None

        for p in cmd_prefixes:
            if text_stripped == p or text_stripped.startswith(p + " "):
                matched_prefix = p
                break

        if not matched_prefix:
            return HookResult()

        cancel_result = HookResult()
        cancel_result.strategy = HookStrategy.CANCEL

        args_str = text_stripped[len(matched_prefix) :].strip()
        tokens = [t.strip().lower() for t in args_str.split() if t.strip()]

        if "stop" in tokens or "стоп" in tokens:
            if self._is_running:
                self._request_stop()
            else:
                BulletinHelper.show_info("Удаление кружков не запущено.")
            return cancel_result

        only_my = self.get_setting("only_my", False)
        limit = 0

        for token in tokens:
            if token in ("my", "мои", "я"):
                only_my = True
            elif token in ("all", "все", "всё"):
                only_my = False
            elif token.isdigit():
                limit = int(token)

        peer_id = getattr(params, "peer", None)
        if peer_id is None:
            BulletinHelper.show_error("❌ Ошибка: не удалось получить ID чата!")
            return cancel_result

        fragment = get_last_fragment()
        activity = fragment.getParentActivity() if fragment else getattr(LaunchActivity, "instance", None)
        self._start_cleaning(activity, account, peer_id, only_my, limit)
        return cancel_result

    def _request_stop(self):
        self._cancel_requested = True
        self._update_progress("⏹️ Остановка процесса...")

    def _show_progress(self, activity, title: str, initial_text: str):
        if not activity or not AlertDialogBuilder:
            return None
        try:
            builder = AlertDialogBuilder(activity, AlertDialogBuilder.ALERT_TYPE_SPINNER)
            builder.set_title(title)
            builder.set_message(initial_text)
            builder.set_positive_button(
                "Остановить",
                lambda bld, which: (bld.dismiss(), self._request_stop())
            )
            builder.show()
            builder.set_cancelable(True)
            builder.set_on_back_button_listener(lambda bld, which: (bld.dismiss(), self._request_stop()))
            return builder
        except Exception as e:
            self.logger.warning(f"Could not show progress dialog: {e}")
            return None

    def _update_progress(self, text: str):
        if self._progress_builder:
            run_on_ui_thread(lambda: self._progress_builder.set_message(text))
        else:
            BulletinHelper.show_info(text)

    def _dismiss_progress(self):
        if self._progress_builder:
            run_on_ui_thread(lambda: self._progress_builder.dismiss())
            self._progress_builder = None

    def _start_cleaning(
        self,
        activity,
        account: int,
        peer_id: Any,
        only_my: bool,
        limit: int,
        raw_chat: Any = None,
        raw_user: Any = None,
    ):
        if self._is_running:
            BulletinHelper.show_error("⚠️ Процесс уже выполняется!")
            return

        self._is_running = True
        self._cancel_requested = False

        # Открываем диалоговое окно прогресса
        self._progress_builder = self._show_progress(
            activity,
            "Circle Cleaner",
            "Инициализация поиска видеосообщений..."
        )

        threading.Thread(
            target=self._run_cleaner,
            args=(account, peer_id, only_my, limit, raw_chat, raw_user),
            daemon=True,
        ).start()

    def _resolve_input_peer(self, account: int, peer_id: Any, raw_chat: Any = None, raw_user: Any = None):
        """Надежное получение InputPeer для MTProto с поддержкой прямых объектов и числовых ID"""
        # 1. Если передан готовый объект Chat (из ChatActivity / context)
        if raw_chat:
            try:
                cid = getattr(raw_chat, "id", 0)
                access_hash = getattr(raw_chat, "access_hash", 0)
                try:
                    from org.telegram.messenger import ChatObject
                    is_chan = ChatObject.isChannel(raw_chat)
                except Exception:
                    is_chan = getattr(raw_chat, "broadcast", False) or getattr(raw_chat, "megagroup", False)

                if is_chan:
                    inp = TLRPC.TL_inputPeerChannel()
                    inp.channel_id = cid
                    inp.access_hash = access_hash
                    return inp
                else:
                    inp = TLRPC.TL_inputPeerChat()
                    inp.chat_id = cid
                    return inp
            except Exception as e:
                self.logger.warning(f"Failed to resolve from raw_chat: {e}")

        # 2. Если передан готовый объект User (из ChatActivity / context)
        if raw_user:
            try:
                inp = TLRPC.TL_inputPeerUser()
                inp.user_id = getattr(raw_user, "id", 0)
                inp.access_hash = getattr(raw_user, "access_hash", 0)
                return inp
            except Exception as e:
                self.logger.warning(f"Failed to resolve from raw_user: {e}")

        try:
            controller = get_messages_controller(account)
        except Exception:
            controller = None
        if not controller:
            try:
                controller = MessagesController.getInstance(account)
            except Exception:
                pass

        if not controller:
            return None

        # 3. Попытка через стандартный метод Telegram getInputPeer
        if peer_id is not None:
            try:
                p_id_int = int(peer_id)
                peer = controller.getInputPeer(p_id_int)
                if peer and not isinstance(peer, TLRPC.TL_inputPeerEmpty):
                    access_hash = getattr(peer, "access_hash", None)
                    if access_hash is not None and access_hash != 0:
                        return peer
            except Exception:
                pass

        # 4. Ручная сборка по числовому значению ID
        if peer_id is not None:
            try:
                did = int(peer_id)
                if did < 0:
                    chat_id = abs(did)
                    # Если супергруппа или канал с префиксом -100xxxxxxxxxx
                    if chat_id > 1000000000000:
                        real_cid = chat_id - 1000000000000
                        chat = controller.getChat(real_cid)
                        inp = TLRPC.TL_inputPeerChannel()
                        inp.channel_id = real_cid
                        inp.access_hash = getattr(chat, "access_hash", 0) if chat else 0
                        return inp
                    else:
                        chat = controller.getChat(chat_id)
                        if chat:
                            try:
                                from org.telegram.messenger import ChatObject
                                is_chan = ChatObject.isChannel(chat)
                            except Exception:
                                is_chan = getattr(chat, "broadcast", False) or getattr(chat, "megagroup", False)

                            if is_chan:
                                inp = TLRPC.TL_inputPeerChannel()
                                inp.channel_id = chat.id
                                inp.access_hash = getattr(chat, "access_hash", 0)
                                return inp
                            else:
                                inp = TLRPC.TL_inputPeerChat()
                                inp.chat_id = chat.id
                                return inp
                        else:
                            inp = TLRPC.TL_inputPeerChat()
                            inp.chat_id = chat_id
                            return inp
                else:
                    # did > 0: может быть как chatId (положительный ID группы), так и userId
                    chat = controller.getChat(did)
                    if chat:
                        try:
                            from org.telegram.messenger import ChatObject
                            is_chan = ChatObject.isChannel(chat)
                        except Exception:
                            is_chan = getattr(chat, "broadcast", False) or getattr(chat, "megagroup", False)

                        if is_chan:
                            inp = TLRPC.TL_inputPeerChannel()
                            inp.channel_id = chat.id
                            inp.access_hash = getattr(chat, "access_hash", 0)
                            return inp
                        else:
                            inp = TLRPC.TL_inputPeerChat()
                            inp.chat_id = chat.id
                            return inp

                    user = controller.getUser(did)
                    if user:
                        inp = TLRPC.TL_inputPeerUser()
                        inp.user_id = user.id
                        inp.access_hash = getattr(user, "access_hash", 0)
                        return inp
            except Exception as e:
                self.logger.error(f"Manual inputPeer resolution failed: {e}")

        return None

    def _send_mtproto(self, req, account: int, timeout: float = 15.0):
        """
        Отправка MTProto запроса с частым освобождением GIL (time.sleep)
        для предотвращения дедлоков в Chaquopy на фоновом потоке.
        """
        box = {"response": None, "error": None, "done": False}

        def on_complete(response, error):
            box["response"] = response
            box["error"] = error
            box["done"] = True

        if RequestCallback is not None:
            try:
                delegate = RequestCallback(on_complete, account=account)
            except Exception:
                delegate = on_complete
        else:
            delegate = on_complete

        req_id = 0
        try:
            req_id = send_request(req, delegate, account=account)
        except Exception as e:
            self.logger.warning(f"send_request helper failed ({e}), using ConnectionsManager")

        if req_id == 0:
            try:
                cm = ConnectionsManager.getInstance(account)
                req_id = cm.sendRequest(req, delegate)
            except Exception as e2:
                raise RuntimeError(f"Не удалось отправить запрос: {e2}")

        if req_id == 0:
            raise RuntimeError("Telegram отклонил отправку запроса (код 0).")

        start_t = time.time()
        while not box["done"] and not self._cancel_requested:
            if time.time() - start_t > timeout:
                raise TimeoutError(f"Сервер не ответил за {int(timeout)} сек.")
            time.sleep(0.08)

        if self._cancel_requested:
            raise RuntimeError("Остановлено пользователем.")

        if box["error"]:
            err = box["error"]
            err_text = getattr(err, "text", str(err))
            raise RuntimeError(err_text)

        return box["response"]

    def _run_cleaner(
        self,
        account: int,
        peer_id: Any,
        only_my: bool,
        limit: int,
        raw_chat: Any = None,
        raw_user: Any = None,
    ):
        try:
            # 1. Проверяем сеть
            try:
                cm = ConnectionsManager.getInstance(account)
                cm.checkConnection()
            except Exception:
                pass

            input_peer = self._resolve_input_peer(account, peer_id, raw_chat=raw_chat, raw_user=raw_user)
            if not input_peer:
                self._dismiss_progress()
                BulletinHelper.show_error("❌ Ошибка: не удалось получить данные чата (InputPeer is None)!")
                return

            mode_str = "только свои" if only_my else "все"
            limit_str = f" (до {limit} шт.)" if limit > 0 else ""
            self._update_progress(f"🔍 Поиск кружков ({mode_str}){limit_str}...")

            collected_ids = []
            seen_ids = set()

            # 2. Быстрый серверный поиск через TL_messages_search
            filter_cls = (
                getattr(TLRPC, "TL_inputMessagesFilterRoundVideo", None)
                or getattr(TLRPC, "TL_inputMessagesFilterRoundVoice", None)
            )

            if filter_cls:
                offset_id = 0
                while not self._cancel_requested:
                    req = TLRPC.TL_messages_search()
                    req.peer = input_peer
                    req.q = ""
                    req.filter = filter_cls()
                    req.offset_id = int(offset_id)
                    req.limit = 100

                    try:
                        res = self._send_mtproto(req, account=account, timeout=10.0)
                    except Exception as e:
                        self.logger.warning(f"Filter search failed/timed out: {e}")
                        break

                    messages = getattr(res, "messages", None)
                    if not messages or messages.isEmpty():
                        break

                    msg_count = messages.size()
                    new_offset = offset_id

                    for i in range(msg_count):
                        if self._cancel_requested:
                            break
                        msg = messages.get(i)
                        if not msg:
                            continue

                        mid = getattr(msg, "id", 0)
                        if mid > 0:
                            new_offset = min(new_offset, mid) if new_offset > 0 else mid

                        if not self._is_round_video(msg):
                            continue
                        if only_my and not getattr(msg, "out", False):
                            continue

                        if mid not in seen_ids:
                            seen_ids.add(mid)
                            collected_ids.append(mid)

                        if limit > 0 and len(collected_ids) >= limit:
                            break

                    self._update_progress(f"🔍 Быстрый поиск...\nНайдено кружков: {len(collected_ids)}")

                    if limit > 0 and len(collected_ids) >= limit:
                        break
                    if msg_count < 100 or new_offset == offset_id:
                        break

                    offset_id = new_offset
                    time.sleep(0.05)

            # 3. Глубокое сканирование через TL_messages_getHistory
            # ЕСЛИ быстрый поиск вернул 0 результатов (или сервер не поддерживает фильтр в этом чате)
            if len(collected_ids) == 0 and not self._cancel_requested:
                self._update_progress("Поиск по фильтру не дал результатов.\nСканирование истории сообщений...")
                offset_id = 0
                scanned_total = 0

                while not self._cancel_requested:
                    h_req = TLRPC.TL_messages_getHistory()
                    h_req.peer = input_peer
                    h_req.offset_id = int(offset_id)
                    h_req.offset_date = 0
                    h_req.add_offset = 0
                    h_req.limit = 100
                    h_req.max_id = 0
                    h_req.min_id = 0
                    h_req.hash = 0

                    try:
                        h_res = self._send_mtproto(h_req, account=account, timeout=12.0)
                    except Exception as e:
                        self.logger.error(f"getHistory failed: {e}")
                        if scanned_total == 0:
                            raise e
                        break

                    msgs = getattr(h_res, "messages", None)
                    if not msgs or msgs.isEmpty():
                        break

                    m_count = msgs.size()
                    new_offset = offset_id

                    for i in range(m_count):
                        if self._cancel_requested:
                            break
                        m = msgs.get(i)
                        if not m:
                            continue

                        scanned_total += 1
                        mid = getattr(m, "id", 0)
                        if mid > 0:
                            new_offset = min(new_offset, mid) if new_offset > 0 else mid

                        if not self._is_round_video(m):
                            continue
                        if only_my and not getattr(m, "out", False):
                            continue

                        if mid not in seen_ids:
                            seen_ids.add(mid)
                            collected_ids.append(mid)

                        if limit > 0 and len(collected_ids) >= limit:
                            break

                    self._update_progress(
                        f"🔍 Сканирование истории сообщений...\n"
                        f"Проверено сообщений: {scanned_total}\n"
                        f"Найдено кружков: {len(collected_ids)}"
                    )

                    if limit > 0 and len(collected_ids) >= limit:
                        break
                    if m_count < 100 or new_offset == offset_id:
                        break

                    offset_id = new_offset
                    time.sleep(0.05)

            if self._cancel_requested:
                self._dismiss_progress()
                BulletinHelper.show_info("⏹️ Поиск отменен.")
                return

            total_found = len(collected_ids)
            if total_found == 0:
                self._dismiss_progress()
                BulletinHelper.show_info(f"ℹ️ Кружков ({mode_str}) в этом чате не найдено.")
                return

            # 4. Пакетное удаление сообщений
            revoke_flag = self.get_setting("revoke", True)
            deleted_count = 0
            chunk_size = 100

            is_channel = (
                isinstance(input_peer, TLRPC.TL_inputPeerChannel)
                or hasattr(input_peer, "channel_id")
                or "Channel" in type(input_peer).__name__
            )

            for chunk_start in range(0, total_found, chunk_size):
                if self._cancel_requested:
                    break

                chunk = collected_ids[chunk_start : chunk_start + chunk_size]
                percent = int((deleted_count / total_found) * 100) if total_found > 0 else 0
                self._update_progress(
                    f"🗑️ Удаление кружков: {deleted_count}/{total_found} ({percent}%)\n"
                    f"Пачка {chunk_start // chunk_size + 1} из {(total_found + chunk_size - 1) // chunk_size}..."
                )

                if is_channel:
                    del_req = TLRPC.TL_channels_deleteMessages()
                    inp_chan = TLRPC.TL_inputChannel()
                    inp_chan.channel_id = getattr(input_peer, "channel_id", 0)
                    inp_chan.access_hash = getattr(input_peer, "access_hash", 0)
                    del_req.channel = inp_chan
                    try:
                        from java.lang import Integer as JavaInt
                        for mid in chunk:
                            del_req.id.add(JavaInt(int(mid)))
                    except Exception:
                        for mid in chunk:
                            del_req.id.add(int(mid))
                else:
                    del_req = TLRPC.TL_messages_deleteMessages()
                    del_req.revoke = revoke_flag
                    try:
                        from java.lang import Integer as JavaInt
                        for mid in chunk:
                            del_req.id.add(JavaInt(int(mid)))
                    except Exception:
                        for mid in chunk:
                            del_req.id.add(int(mid))

                try:
                    self._send_mtproto(del_req, account=account, timeout=15.0)
                    deleted_count += len(chunk)
                except Exception as e:
                    self.logger.error(f"Delete request failed: {e}")
                    self._dismiss_progress()
                    BulletinHelper.show_error(f"❌ Ошибка при удалении: {e}\n(Удалено: {deleted_count})")
                    return

                time.sleep(0.2)

            self._dismiss_progress()

            if self._cancel_requested:
                BulletinHelper.show_info(f"⏹️ Остановлено. Удалено: {deleted_count}/{total_found}")
            else:
                BulletinHelper.show_success(f"✅ Готово! Удалено кружков: {deleted_count}")

        except Exception as global_err:
            self._dismiss_progress()
            self.logger.error(f"Cleaner unhandled error: {global_err}")
            BulletinHelper.show_error(f"❌ Ошибка: {global_err}")

        finally:
            self._is_running = False
            self._cancel_requested = False
            self._dismiss_progress()

    def _is_round_video(self, msg) -> bool:
        """
        Проверяет, является ли сообщение видеосообщением (кружком).
        Использует множество проверок:
        1. MessageObject.isRoundVideo()
        2. MessageObject.isRoundVideoMessage()
        3. MessageObject.isRoundVideoDocument()
        4. document.attributes: round_message flag
        """
        if not msg:
            return False

        # 1. Если это MessageObject (из Telegram UI)
        try:
            if hasattr(msg, "isRoundVideo") and callable(msg.isRoundVideo):
                if msg.isRoundVideo():
                    return True
        except Exception:
            pass

        raw_msg = getattr(msg, "messageOwner", msg)

        # 2. Через нативный метод Telegram MessageObject.isRoundVideoMessage
        try:
            from org.telegram.messenger import MessageObject
            if MessageObject.isRoundVideoMessage(raw_msg):
                return True
        except Exception:
            pass

        # 3. Через нативный метод MessageObject.isRoundVideoDocument
        try:
            from org.telegram.messenger import MessageObject
            doc = getattr(getattr(raw_msg, "media", None), "document", None)
            if doc and hasattr(MessageObject, "isRoundVideoDocument"):
                if MessageObject.isRoundVideoDocument(doc):
                    return True
        except Exception:
            pass

        # 4. Проверка через медиа и атрибуты документа MTProto
        try:
            media = getattr(raw_msg, "media", None)
            if not media:
                return False
            doc = getattr(media, "document", None)
            if not doc:
                return False
            attrs = getattr(doc, "attributes", None)
            if not attrs:
                return False

            size = attrs.size() if hasattr(attrs, "size") else len(attrs)
            for i in range(size):
                attr = attrs.get(i) if hasattr(attrs, "get") else attrs[i]
                if not attr:
                    continue

                if getattr(attr, "round_message", False):
                    return True

                cls_name = getattr(attr, "__class__", type(attr)).__name__
                if "Video" in cls_name and getattr(attr, "round_message", False):
                    return True
        except Exception:
            pass

        return False
