"""
Circle Cleaner Plugin for exteraGram / AyuGram (Android)
Удаление видеосообщений (кружков) через кнопку Plugins в чате или текстовой командой.
Построен на нативном механизме Telegram MessagesController.deleteMessages с защитой от ошибок сигнатур.
"""

import threading
import time
from typing import Any, Dict, List

from android_utils import log, run_on_ui_thread
from base_plugin import BasePlugin, HookResult, HookStrategy, MenuItemData, MenuItemType
from client_utils import get_last_fragment, get_messages_controller, get_user_config, send_request
from java.lang import Integer, Long
from java.util import ArrayList
from org.telegram.messenger import ChatObject, MessagesController, UserConfig
from org.telegram.tgnet import TLRPC
from ui.alert import AlertDialogBuilder
from ui.bulletin import BulletinHelper
from ui.settings import Divider, Header, Switch, Text

try:
    from org.telegram.ui import LaunchActivity
except Exception:
    LaunchActivity = None


__id__ = "circle_cleaner"
__name__ = "Circle Cleaner"
__description__ = "Удаление видеосообщений (кружков) из чата через кнопку меню Plugins или команду"
__author__ = "VANTA"
__version__ = "1.5.1"
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

        self._is_running = False
        self._cancel_requested = False
        self._progress_builder = None
        self.logger.info("Circle Cleaner v1.5.1 loaded successfully!")

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
        try:
            dialog_id = context.get("dialog_id")
            if not dialog_id:
                fragment = context.get("fragment") or get_last_fragment()
                if fragment and hasattr(fragment, "getDialogId"):
                    dialog_id = fragment.getDialogId()

            if not dialog_id:
                raw_chat = context.get("chat")
                if raw_chat:
                    cid = getattr(raw_chat, "id", 0)
                    is_chan = getattr(raw_chat, "broadcast", False) or getattr(raw_chat, "megagroup", False)
                    dialog_id = (-1000000000000 - cid) if is_chan else -cid
                elif context.get("user"):
                    dialog_id = getattr(context.get("user"), "id", 0)
                elif context.get("message"):
                    dialog_id = getattr(context.get("message"), "dialog_id", 0)

            if not dialog_id:
                BulletinHelper.show_info("ℹ️ Откройте чат и выберите 'Удалить кружочки' в меню (3 точки) или зажмите любое сообщение.")
                return

            dialog_id = int(dialog_id)
            account = context.get("account")
            if account is None:
                account = UserConfig.selectedAccount

            fragment = context.get("fragment") or get_last_fragment()
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
                        log(f"Error showing stop dialog: {e}")
                        self._request_stop()

                run_on_ui_thread(show_stop_dialog)
                return

            # Показываем всплывающий диалог выбора режима удаления
            def show_picker_dialog():
                if not activity or not AlertDialogBuilder:
                    default_only_my = self.get_setting("only_my", False)
                    self._start_cleaning(activity, account, dialog_id, only_my=default_only_my, limit=0)
                    return

                try:
                    builder = AlertDialogBuilder(activity)
                    builder.set_title("Удаление кружочков")
                    builder.set_message("Какие видеосообщения (кружки) удалить из этого чата?")

                    builder.set_positive_button(
                        "Все кружки",
                        lambda bld, which: (
                            bld.dismiss(),
                            self._start_cleaning(activity, account, dialog_id, only_my=False, limit=0)
                        )
                    )
                    builder.set_negative_button(
                        "Только мои",
                        lambda bld, which: (
                            bld.dismiss(),
                            self._start_cleaning(activity, account, dialog_id, only_my=True, limit=0)
                        )
                    )
                    builder.set_neutral_button("Отмена", lambda bld, which: bld.dismiss())
                    builder.show()
                    builder.make_button_red(AlertDialogBuilder.BUTTON_POSITIVE)
                except Exception as e:
                    log(f"Error showing picker dialog: {e}")
                    default_only_my = self.get_setting("only_my", False)
                    self._start_cleaning(activity, account, dialog_id, only_my=default_only_my, limit=0)

            run_on_ui_thread(show_picker_dialog)
        except Exception as e:
            log(f"on_chat_menu_click error: {e}")

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

        dialog_id = int(peer_id)
        fragment = get_last_fragment()
        activity = fragment.getParentActivity() if fragment else getattr(LaunchActivity, "instance", None)
        self._start_cleaning(activity, account, dialog_id, only_my, limit)
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

    def _start_cleaning(self, activity, account: int, dialog_id: int, only_my: bool, limit: int):
        if self._is_running:
            BulletinHelper.show_error("⚠️ Процесс уже выполняется!")
            return

        self._is_running = True
        self._cancel_requested = False

        self._progress_builder = self._show_progress(
            activity,
            "Circle Cleaner",
            "Инициализация поиска видеосообщений..."
        )

        threading.Thread(
            target=self._run_cleaner,
            args=(account, dialog_id, only_my, limit),
            daemon=True,
        ).start()

    def request(self, req: Any, account: int, timeout: float = 15.0) -> Any:
        """Отправка MTProto запроса через send_request с освобождением GIL"""
        while True:
            if self._cancel_requested:
                raise RuntimeError("Остановлено пользователем")

            done = threading.Event()
            result = {}

            def callback(response, error):
                result["response"], result["error"] = response, error
                done.set()

            send_request(req, callback, account=account)

            start_t = time.time()
            while not done.is_set() and not self._cancel_requested:
                if time.time() - start_t > timeout:
                    raise TimeoutError(f"Сервер не ответил за {int(timeout)} сек.")
                time.sleep(0.08)

            if self._cancel_requested:
                raise RuntimeError("Остановлено пользователем")

            error = result.get("error")
            if not error:
                return result.get("response")

            err_text = getattr(error, "text", str(error))
            if err_text.startswith("FLOOD_WAIT_"):
                wait_sec = int(err_text.rsplit("_", 1)[1])
                self._update_progress(f"⏳ Ожидание Telegram (Flood Wait: {wait_sec} сек)...")
                time.sleep(wait_sec)
                continue

            raise RuntimeError(err_text)

    def delete_batch(self, account: int, dialog_id: int, ids_list: List[int], revoke: bool = True):
        """Удаление пачки сообщений с многоуровневой защитой от ошибок типов"""
        controller = get_messages_controller(account)
        if not controller:
            controller = MessagesController.getInstance(account)

        ids = ArrayList()
        for message_id in ids_list:
            ids.add(Integer(int(message_id)))

        did = int(dialog_id)
        done = threading.Event()
        errors = []

        def task():
            try:
                # 1. Точный вызов нативного метода Telegram (как в del_my_msgs)
                try:
                    controller.deleteMessages(ids, None, None, did, 0, bool(revoke), 0)
                    return
                except Exception as e1:
                    log(f"[CC] deleteMessages attempt 1 error: {e1}")

                # 2. Вызов без параметра topicId (для сборок без поддержки тем/форумов)
                try:
                    controller.deleteMessages(ids, None, None, did, bool(revoke), 0)
                    return
                except Exception as e2:
                    log(f"[CC] deleteMessages attempt 2 error: {e2}")

                # 3. Вызов с явной Long оберткой
                try:
                    controller.deleteMessages(ids, None, None, Long(did), 0, bool(revoke), 0)
                    return
                except Exception as e3:
                    log(f"[CC] deleteMessages attempt 3 error: {e3}")

                # 4. Резервный MTProto-запрос если контроллер отклонил все сигнатуры
                is_chan = (did < 0 and abs(did) > 1000000000000)
                if is_chan:
                    chan_id = abs(did) - 1000000000000
                    chat = controller.getChat(Long(chan_id))
                    del_req = TLRPC.TL_channels_deleteMessages()
                    inp_chan = TLRPC.TL_inputChannel()
                    inp_chan.channel_id = chan_id
                    inp_chan.access_hash = getattr(chat, "access_hash", 0) if chat else 0
                    del_req.channel = inp_chan
                    for mid in ids_list:
                        del_req.id.add(Integer(int(mid)))
                else:
                    del_req = TLRPC.TL_messages_deleteMessages()
                    del_req.revoke = bool(revoke)
                    for mid in ids_list:
                        del_req.id.add(Integer(int(mid)))

                self.request(del_req, account=account)
            except Exception as e_final:
                errors.append(e_final)
            finally:
                done.set()

        run_on_ui_thread(task)
        done.wait()
        if errors:
            raise errors[0]

    def _resolve_peer(self, controller, dialog_id: int):
        """Безопасное получение InputPeer"""
        did = int(dialog_id)
        try:
            peer = controller.getInputPeer(did)
            if peer and not isinstance(peer, TLRPC.TL_inputPeerEmpty):
                return peer
        except Exception:
            pass

        # Ручная сборка если getInputPeer вернул Empty
        if did < 0:
            chat_id = abs(did)
            if chat_id > 1000000000000:
                real_cid = chat_id - 1000000000000
                chat = controller.getChat(Long(real_cid))
                peer = TLRPC.TL_inputPeerChannel()
                peer.channel_id = real_cid
                peer.access_hash = getattr(chat, "access_hash", 0) if chat else 0
                return peer
            else:
                chat = controller.getChat(Long(chat_id))
                if chat and (getattr(chat, "broadcast", False) or getattr(chat, "megagroup", False)):
                    peer = TLRPC.TL_inputPeerChannel()
                    peer.channel_id = chat.id
                    peer.access_hash = getattr(chat, "access_hash", 0)
                    return peer
                else:
                    peer = TLRPC.TL_inputPeerChat()
                    peer.chat_id = chat_id
                    return peer
        else:
            user = controller.getUser(Long(did))
            peer = TLRPC.TL_inputPeerUser()
            peer.user_id = did
            peer.access_hash = getattr(user, "access_hash", 0) if user else 0
            return peer

    def _run_cleaner(self, account: int, dialog_id: int, only_my: bool, limit: int):
        try:
            mode_str = "только свои" if only_my else "все"
            limit_str = f" (до {limit} шт.)" if limit > 0 else ""
            self._update_progress(f"🔍 Поиск кружков ({mode_str}){limit_str}...")

            controller = get_messages_controller(account)
            if not controller:
                controller = MessagesController.getInstance(account)

            input_peer = self._resolve_peer(controller, dialog_id)
            seen = set()
            collected_ids = []
            scanned_total = 0
            max_date = 0

            # 1. Проверяем, работает ли быстрый фильтр RoundVideo
            filter_cls = (
                getattr(TLRPC, "TL_inputMessagesFilterRoundVideo", None)
                or getattr(TLRPC, "TL_inputMessagesFilterRoundVoice", None)
            )

            fast_search_worked = False
            if filter_cls:
                try:
                    req = TLRPC.TL_messages_search()
                    req.peer = input_peer
                    req.q = ""
                    req.filter = filter_cls()
                    req.limit = 100
                    req.offset_id = 0

                    res = self.request(req, account=account, timeout=8.0)
                    msgs = getattr(res, "messages", None)
                    if msgs and not msgs.isEmpty():
                        for i in range(msgs.size()):
                            m = msgs.get(i)
                            if isinstance(m, TLRPC.TL_messageEmpty) or getattr(m, "id", 0) <= 0:
                                continue
                            if self._is_round_video(m):
                                fast_search_worked = True
                                break
                except Exception as e:
                    self.logger.warning(f"Fast search probe: {e}")

            # Если быстрый фильтр нашел кружки — используем его, иначе полный поиск Empty (100% покрытие)
            target_filter = filter_cls() if (filter_cls and fast_search_worked) else TLRPC.TL_inputMessagesFilterEmpty()

            if not fast_search_worked:
                self._update_progress(f"🔍 Сканирование сообщений чата ({mode_str})...")

            # 2. Постраничное сканирование сообщений через сдвиг дат max_date
            while not self._cancel_requested:
                before = len(seen)
                window_min_date = None
                offset_id = 0

                while not self._cancel_requested:
                    req = TLRPC.TL_messages_search()
                    req.peer = input_peer
                    req.q = ""
                    req.filter = target_filter
                    req.limit = 100
                    req.offset_id = offset_id
                    req.max_date = max_date

                    try:
                        res = self.request(req, account=account, timeout=15.0)
                    except Exception as e:
                        self.logger.error(f"Search request failed: {e}")
                        break

                    messages = getattr(res, "messages", None)
                    if not messages or messages.isEmpty():
                        break

                    batch = [messages.get(i) for i in range(messages.size())]
                    if not batch:
                        break

                    for m in batch:
                        if self._cancel_requested:
                            break
                        if isinstance(m, TLRPC.TL_messageEmpty) or getattr(m, "id", 0) <= 0:
                            continue

                        m_date = getattr(m, "date", 0)
                        if window_min_date is None or m_date < window_min_date:
                            window_min_date = m_date

                        mid = m.id
                        if mid in seen:
                            continue
                        seen.add(mid)
                        scanned_total += 1

                        if not self._is_round_video(m):
                            continue
                        if only_my and not getattr(m, "out", False):
                            continue

                        collected_ids.append(mid)
                        if limit > 0 and len(collected_ids) >= limit:
                            break

                    self._update_progress(
                        f"🔍 Сканирование сообщений...\n"
                        f"Проверено сообщений: {scanned_total}\n"
                        f"Найдено кружков: {len(collected_ids)}"
                    )

                    if limit > 0 and len(collected_ids) >= limit:
                        break

                    new_offset = min(m.id for m in batch)
                    if offset_id != 0 and new_offset >= offset_id:
                        break
                    offset_id = new_offset

                if limit > 0 and len(collected_ids) >= limit:
                    break
                if len(seen) == before or window_min_date is None:
                    break
                max_date = window_min_date

            if self._cancel_requested:
                self._dismiss_progress()
                BulletinHelper.show_info("⏹️ Поиск отменен.")
                return

            total_found = len(collected_ids)
            if total_found == 0:
                self._dismiss_progress()
                BulletinHelper.show_info(f"ℹ️ Кружков ({mode_str}) в этом чате не найдено.")
                return

            # 3. Удаление сообщений через надежный delete_batch
            revoke_flag = self.get_setting("revoke", True)
            deleted_count = 0
            chunk_size = 100

            for chunk_start in range(0, total_found, chunk_size):
                if self._cancel_requested:
                    break

                chunk = collected_ids[chunk_start : chunk_start + chunk_size]
                percent = int((deleted_count / total_found) * 100) if total_found > 0 else 0
                self._update_progress(
                    f"🗑️ Удаление кружков: {deleted_count}/{total_found} ({percent}%)\n"
                    f"Пачка {chunk_start // chunk_size + 1} из {(total_found + chunk_size - 1) // chunk_size}..."
                )

                try:
                    self.delete_batch(account, dialog_id, chunk, revoke=revoke_flag)
                    deleted_count += len(chunk)
                except Exception as e:
                    self.logger.error(f"Delete batch failed: {e}")
                    self._dismiss_progress()
                    BulletinHelper.show_error(f"❌ Ошибка при удалении: {e}\n(Удалено: {deleted_count})")
                    return

                time.sleep(0.3)

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
        1. MessageObject.isRoundVideo()
        2. MessageObject.isRoundVideoMessage()
        3. MessageObject.isRoundVideoDocument()
        4. document.attributes: round_message flag
        """
        if not msg:
            return False

        # 1. Если это MessageObject
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
            media = getattr(raw_msg, "media", None)
            doc = getattr(media, "document", None) if media else None
            if doc and hasattr(MessageObject, "isRoundVideoDocument"):
                if MessageObject.isRoundVideoDocument(doc):
                    return True
        except Exception:
            pass

        # 4. Проверка через медиа и атрибуты документа MTProto
        try:
            media = getattr(raw_msg, "media", None)
            doc = getattr(media, "document", None) if media else None
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
