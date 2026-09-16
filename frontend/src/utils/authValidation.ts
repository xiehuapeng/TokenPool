export type AuthMode = "login" | "register" | "reset";

const USERNAME_PATTERN = /^[a-zA-Z0-9][a-zA-Z0-9_.-]{1,62}[a-zA-Z0-9]$/;
const INVITE_CODE_PATTERN = /^[a-zA-Z0-9_-]{8,64}$/;

export function validateCredentials(
  mode: AuthMode,
  username: string,
  password: string,
): string | null {
  if (mode === "login") {
    if (username.length < 2 || username.length > 64) {
      return "请输入 2–64 位用户名";
    }
    if (password.length < 8 || password.length > 256) {
      return "请输入 8–256 位密码";
    }
    return null;
  }

  // Both register and reset create a usable credential, so they share the
  // stronger username and password rules.
  if (!USERNAME_PATTERN.test(username)) {
    return "用户名需为 3–64 位，以字母或数字开头和结尾，中间可使用 . _ -";
  }
  if (
    password.length < 8 ||
    password.length > 64 ||
    !/[A-Za-z]/.test(password) ||
    !/\d/.test(password)
  ) {
    return "密码需为 8–64 位，并且至少包含一个字母和一个数字";
  }
  return null;
}

export function validateInviteCode(inviteCode: string): string | null {
  if (!INVITE_CODE_PATTERN.test(inviteCode.trim())) {
    return "请输入 8–64 位邀请码，仅可使用字母、数字、下划线和连字符";
  }
  return null;
}
