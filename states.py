from aiogram.fsm.state import State, StatesGroup


class Verification(StatesGroup):
    vk = State()
    discord = State()
    forum = State()
    age = State()
    timezone = State()
    tg_username = State()
    email = State()


class ReportFlow(StatesGroup):
    waiting_screens = State()


class InactiveFlow(StatesGroup):
    waiting_dates = State()
    waiting_reason = State()


class ExtraWorkFlow(StatesGroup):
    waiting_screens = State()
    waiting_description = State()


class RemovePunishmentFlow(StatesGroup):
    waiting_proof = State()


class AddUserFlow(StatesGroup):
    waiting_id = State()
    waiting_nick = State()
    waiting_org = State()
    waiting_rank = State()


class RemoveUserFlow(StatesGroup):
    waiting_user = State()
    waiting_reason = State()


class GrantRoleFlow(StatesGroup):
    waiting_user = State()
    waiting_role = State()
    waiting_org_or_group = State()
    waiting_org_in_group = State()


class PointsFlow(StatesGroup):
    waiting_amount = State()
    waiting_reason = State()


class PunishmentFlow(StatesGroup):
    waiting_action = State()   # выдать / снять
    waiting_type = State()     # выговор / пред / устник
    waiting_user = State()
    waiting_reason = State()


class DecisionReasonFlow(StatesGroup):
    waiting_reason = State()


class RemovePunishRequestFlow(StatesGroup):
    waiting_proof = State()


class SettingsFlow(StatesGroup):
    waiting_new_nick = State()


class LeadershipAssignFlow(StatesGroup):
    waiting_user = State()


class SetNormFlow(StatesGroup):
    waiting_org = State()
    waiting_rank = State()
    waiting_vch = State()
    waiting_interview = State()
    waiting_lecture = State()
    waiting_training = State()
    waiting_rp = State()
    waiting_online_hours = State()


class BroadcastFlow(StatesGroup):
    pass  # /o [текст] обрабатывается напрямую из аргументов команды


class SetInfoFlow(StatesGroup):
    pass  # /setinfo [текст] обрабатывается напрямую из аргументов команды


class FrapsFlow(StatesGroup):
    waiting_nick = State()
    waiting_org = State()
    waiting_link = State()


class ResetPasswordFlow(StatesGroup):
    waiting_user = State()
    waiting_password = State()
