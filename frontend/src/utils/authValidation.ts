export type AuthMode = "login" | "register";

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

  if (!/^[a-zA-Z0-9][a-zA-Z0-9_.-]{1,62}[a-zA-Z0-9]$/.test(username)) {
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
