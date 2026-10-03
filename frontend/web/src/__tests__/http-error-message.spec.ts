/**
 * Web 端错误提示口径守卫
 *
 * 锁住两件事：
 * 1. 任意非成功业务码都**优先展示后端 `data.msg`**（后端错误码已收敛为单一事实来源
 *    `RET.code → HTTP status`，前端不再按业务码白名单挑文案），只有后端没给 msg 时
 *    才按「业务码 → 状态码 → 通用」回退到本地文案；`handleError` 同口径。
 * 2. 既有分支行为不变：401 静默续期（含重放）、403 提示、请求取消、网络错误、Blob 下载。
 *
 * 实现方式：给 `request` 实例装一个自定义 adapter，让请求真实穿过响应拦截器，
 * 而不依赖 jsdom 的网络能力；`ElMessage` / i18n / Auth 全部替换为可断言替身。
 *
 * 注意：`ResultEnum` 是 `const enum`，在 isolatedModules 下无法在运行时导入
 * （见 smoke.spec.ts 的同类说明），因此本文件用字面量并在注释里标注对应枚举：
 * SUCCESS=0、ERROR=1、EXCEPTION=-1、UNAUTHORIZED=10403、TOKEN_EXPIRED=10401。
 */
import type { AxiosResponse, InternalAxiosRequestConfig } from "axios";
import { AxiosError } from "axios";
import { beforeEach, describe, expect, it, vi } from "vitest";

// jsdom + undici 的 `Response` 不把 jsdom 的 Blob 当 BodyInit（会退化成 "[object Blob]"），
// 而被测代码解析第三方错误体时只用到 `new Response(blob).text()`。
// 这里覆盖为本测试用的最小实现，语义与浏览器里 `new Response(blob).text()` 一致。
class ResponseShim {
  constructor(private readonly body: Blob) {}
  async text(): Promise<string> {
    return await this.body.text();
  }
}
try {
  Object.defineProperty(globalThis, "Response", {
    value: ResponseShim,
    configurable: true,
    writable: true,
  });
} catch {
  // 环境不允许重定义 Response 时忽略：仅 Blob 用例会受环境差异影响
}

// ────────────── 隔离重型依赖 ──────────────
const mocks = vi.hoisted(() => ({
  error: vi.fn(),
  success: vi.fn(),
  refreshToken: vi.fn(),
  redirectToLogin: vi.fn(),
  setTokens: vi.fn(),
  getAccessToken: vi.fn(),
  getRefreshToken: vi.fn(),
  getRememberMe: vi.fn(),
}));

vi.mock("element-plus", () => ({
  ElMessage: { error: mocks.error, success: mocks.success },
}));

vi.mock("@/locales", () => ({
  // 用可断言前缀替代真实翻译，避免用例耦合 i18n 文案本身
  $t: (key: string) => `i18n:${key}`,
}));

vi.mock("@/utils/auth", () => ({
  Auth: {
    getAccessToken: mocks.getAccessToken,
    getRefreshToken: mocks.getRefreshToken,
    getRememberMe: mocks.getRememberMe,
    setTokens: mocks.setTokens,
  },
  redirectToLogin: mocks.redirectToLogin,
}));

vi.mock("@/api/module_system/auth", () => ({
  default: { refreshToken: mocks.refreshToken },
}));

import { HttpError, handleError, request } from "@/utils/http";

// ────────────── adapter 脚手架 ──────────────

type Preset =
  | { kind: "ok"; data: unknown }
  | { kind: "fail"; status: number; data: unknown }
  | { kind: "throw"; error: Error };

let presets: Preset[] = [];
/** 每次 adapter 被调用时收到的配置（用于断言令牌注入/重放） */
let seenConfigs: InternalAxiosRequestConfig[] = [];

function preset(...items: Preset[]): void {
  presets.push(...items);
}

function ok(data: unknown): Preset {
  return { kind: "ok", data };
}

/** 构造带响应体的 AxiosError —— reject 后进入响应拦截器的错误分支 */
function buildHttpError(
  config: InternalAxiosRequestConfig,
  status: number,
  data: unknown
): AxiosError<ApiResponse> {
  const response = {
    data,
    status,
    statusText: String(status),
    headers: {},
    config,
  } as unknown as AxiosResponse<ApiResponse>;
  return new AxiosError<ApiResponse>(
    `Request failed with status code ${status}`,
    "ERR_BAD_RESPONSE",
    config,
    null,
    response
  );
}

/** 捕获 reject 值，便于断言 message / code */
async function captureError(promise: Promise<unknown>): Promise<unknown> {
  try {
    await promise;
  } catch (error) {
    return error;
  }
  throw new Error("预期请求失败，但请求成功了");
}

beforeEach(() => {
  vi.clearAllMocks();
  presets = [];
  seenConfigs = [];
  mocks.getAccessToken.mockReturnValue("token-1");
  mocks.getRefreshToken.mockReturnValue("refresh-1");
  mocks.getRememberMe.mockReturnValue(false);

  request.defaults.adapter = async (config) => {
    const requestConfig = config as InternalAxiosRequestConfig;
    seenConfigs.push(requestConfig);
    const next = presets.shift();
    if (!next) throw new Error("adapter: 没有更多预设响应");
    if (next.kind === "ok") {
      return {
        data: next.data,
        status: 200,
        statusText: "OK",
        headers: {},
        config: requestConfig,
      } as AxiosResponse;
    }
    if (next.kind === "fail") throw buildHttpError(requestConfig, next.status, next.data);
    throw next.error;
  };
});

// ────────────── 1. 新场景：非白名单业务码优先展示后端 msg ──────────────

describe("业务错误：优先展示后端 data.msg（不再按业务码白名单取文案）", () => {
  it("HTTP 500 + code=4500（服务端错误）展示后端 msg，而不是通用「请求失败」", async () => {
    preset({
      kind: "fail",
      status: 500,
      data: { code: 4500, msg: "分页查询失败: 连接已断开", data: null },
    });

    const error = await captureError(request.get("/demo"));

    expect(mocks.error).toHaveBeenCalledTimes(1);
    expect(mocks.error).toHaveBeenCalledWith("分页查询失败: 连接已断开");
    expect((error as HttpError).message).toBe("分页查询失败: 连接已断开");
    expect(error).toBeInstanceOf(HttpError);
    expect((error as HttpError).code).toBe(500);
  });

  it("HTTP 404 + code=404（资源不存在）展示后端 msg", async () => {
    preset({
      kind: "fail",
      status: 404,
      data: { code: 404, msg: "数据表 tables_0 不存在", data: null },
    });

    const error = await captureError(request.get("/demo"));

    expect(mocks.error).toHaveBeenCalledWith("数据表 tables_0 不存在");
    expect((error as HttpError).message).toBe("数据表 tables_0 不存在");
    expect((error as HttpError).code).toBe(404);
  });

  it("HTTP 409 + 任意业务码也展示后端 msg（未来新增码不再被吞掉）", async () => {
    preset({
      kind: "fail",
      status: 409,
      data: { code: 4090, msg: "该菜单已被其他用户修改，请刷新后重试", data: null },
    });

    await captureError(request.get("/demo"));

    expect(mocks.error).toHaveBeenCalledWith("该菜单已被其他用户修改，请刷新后重试");
  });

  it("后端未给 msg 时按状态码兜底（500 → internalServerError）", async () => {
    preset({ kind: "fail", status: 500, data: { code: 4500, data: null } });

    await captureError(request.get("/demo"));

    expect(mocks.error).toHaveBeenCalledWith("i18n:httpMsg.internalServerError");
  });

  it("后端未给 msg 时按状态码兜底（404 → notFound）", async () => {
    preset({ kind: "fail", status: 404, data: { code: 404, data: null } });

    await captureError(request.get("/demo"));

    expect(mocks.error).toHaveBeenCalledWith("i18n:httpMsg.notFound");
  });

  it("保留历史口径：HTTP 400 + code=1 且无 msg → 通用「请求失败」", async () => {
    preset({ kind: "fail", status: 400, data: { code: 1, data: null } });

    const error = await captureError(request.get("/demo"));

    expect(mocks.error).toHaveBeenCalledWith("i18n:httpMsg.requestFailed");
    expect((error as HttpError).code).toBe(400);
  });

  it("保留历史口径：HTTP 500 + code=-1（EXCEPTION）且无 msg → internalServerError", async () => {
    preset({ kind: "fail", status: 500, data: { code: -1, data: null } });

    await captureError(request.get("/demo"));

    expect(mocks.error).toHaveBeenCalledWith("i18n:httpMsg.internalServerError");
  });

  it("code=10403（UNAUTHORIZED）且 HTTP 非 401 时仍映射为未授权", async () => {
    preset({ kind: "fail", status: 200, data: { code: 10403, msg: "会话已失效", data: null } });

    const error = await captureError(request.get("/demo"));

    expect(mocks.error).toHaveBeenCalledWith("会话已失效");
    expect((error as HttpError).code).toBe(401);
  });
});

// ────────────── 2. 既有分支：403 / 取消 / 网络错误 / Blob ──────────────

describe("既有分支行为不变", () => {
  it("403 优先展示后端 msg，code 仍为 403", async () => {
    preset({ kind: "fail", status: 403, data: { code: 4030, msg: "缺少 module_system:user:delete 权限" } });

    const error = await captureError(request.get("/demo"));

    expect(mocks.error).toHaveBeenCalledWith("缺少 module_system:user:delete 权限");
    expect((error as HttpError).code).toBe(403);
  });

  it("403 无 msg 时回退到 forbidden 文案", async () => {
    preset({ kind: "fail", status: 403, data: { code: 4030 } });

    await captureError(request.get("/demo"));

    expect(mocks.error).toHaveBeenCalledWith("i18n:httpMsg.forbidden");
  });

  it("请求取消（ERR_CANCELED）静默处理，不弹提示", async () => {
    const canceled = new AxiosError("canceled", "ERR_CANCELED");
    preset({ kind: "throw", error: canceled });

    const error = await captureError(request.get("/demo"));

    expect(mocks.error).not.toHaveBeenCalled();
    expect((error as HttpError).message).toBe("i18n:httpMsg.requestCancelled");
  });

  it("网络错误（无 response）给出网络提示", async () => {
    preset({ kind: "throw", error: new AxiosError("Network Error") });

    const error = await captureError(request.get("/demo"));

    // 既有分支：命中 "Network Error" 给出专用文案（非 i18n key）
    expect(mocks.error).toHaveBeenCalledWith("网络连接错误，请检查您的网络设置");
    expect((error as Error).message).toBe("网络连接错误，请检查您的网络设置");
  });

  it("Blob 下载错误：code=1 时展示错误体里的 msg（既有分支）", async () => {
    const blob = new Blob([JSON.stringify({ code: 1, msg: "文件不存在或已被删除" })]);
    preset({ kind: "fail", status: 400, data: blob });

    const error = await captureError(request.get("/demo", { responseType: "blob" }));

    expect(mocks.error).toHaveBeenCalledWith("文件不存在或已被删除");
    expect((error as Error).message).toBe("文件不存在或已被删除");
  });
});

// ────────────── 2b. Blob 下载错误：任意业务码都取后端 msg ──────────────

/** 构造下载响应：responseType=blob 的失败响应 */
function presetBlobFailure(status: number, body: Blob | string): void {
  preset({ kind: "fail", status, data: typeof body === "string" ? new Blob([body]) : body });
}

const blobExport = () => request.get("/demo/export", { responseType: "blob" });

describe("Blob 下载错误：解析错误体并优先展示后端 msg", () => {
  it("code=4500（内部故障）展示后端 msg，而不是通用文案", async () => {
    presetBlobFailure(500, JSON.stringify({ code: 4500, msg: "导出失败: 磁盘空间不足" }));

    const error = await captureError(blobExport());

    expect(mocks.error).toHaveBeenCalledTimes(1);
    expect(mocks.error).toHaveBeenCalledWith("导出失败: 磁盘空间不足");
    expect((error as HttpError).message).toBe("导出失败: 磁盘空间不足");
    expect(error).toBeInstanceOf(HttpError);
    expect((error as HttpError).code).toBe(500);
  });

  it("code=404（资源不存在）展示后端 msg", async () => {
    presetBlobFailure(404, JSON.stringify({ code: 404, msg: "待导出的记录已不存在" }));

    const error = await captureError(blobExport());

    expect(mocks.error).toHaveBeenCalledWith("待导出的记录已不存在");
    expect((error as HttpError).code).toBe(404);
  });

  it("code=4090（未来新增的业务码）同样展示后端 msg", async () => {
    presetBlobFailure(409, JSON.stringify({ code: 4090, msg: "该导出任务已被取消" }));

    await captureError(blobExport());

    expect(mocks.error).toHaveBeenCalledWith("该导出任务已被取消");
  });

  it("有业务码但无 msg 时保留原有 1/-1 兜底文案（code=1）", async () => {
    presetBlobFailure(400, JSON.stringify({ code: 1 }));

    await captureError(blobExport());

    expect(mocks.error).toHaveBeenCalledWith("i18n:httpMsg.requestFailed");
  });

  it("有业务码但无 msg 时保留原有 1/-1 兜底文案（code=-1）", async () => {
    presetBlobFailure(500, JSON.stringify({ code: -1 }));

    await captureError(blobExport());

    expect(mocks.error).toHaveBeenCalledWith("i18n:httpMsg.internalServerError");
  });

  it("非 1/-1 的业务码且无 msg 时按 HTTP 状态码兜底（500 → internalServerError）", async () => {
    presetBlobFailure(500, JSON.stringify({ code: 4500 }));

    const error = await captureError(blobExport());

    expect(mocks.error).toHaveBeenCalledWith("i18n:httpMsg.internalServerError");
    expect((error as HttpError).code).toBe(500);
  });

  it("非 JSON 的二进制 Blob 不抛额外异常，按 HTTP 状态码兜底并 reject", async () => {
    // PNG magic bytes：真二进制内容，JSON.parse 必然失败
    presetBlobFailure(500, new Blob([new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a])]));

    const error = await captureError(blobExport());

    expect(error).toBeInstanceOf(HttpError);
    expect((error as HttpError).message).toBe("i18n:httpMsg.internalServerError");
    expect((error as HttpError).code).toBe(500);
    expect(mocks.error).toHaveBeenCalledWith("i18n:httpMsg.internalServerError");
  });

  it("空 Blob（下载中断/空响应体）不抛额外异常，按 HTTP 状态码兜底", async () => {
    presetBlobFailure(404, new Blob([]));

    const error = await captureError(blobExport());

    expect(error).toBeInstanceOf(HttpError);
    expect((error as HttpError).code).toBe(404);
    expect((error as HttpError).message).toBe("i18n:httpMsg.notFound");
  });

  it("错误体读取本身失败（下载中断）不抛额外异常，按 HTTP 状态码兜底", async () => {
    const unreadable = new Blob(["partial"]);
    Object.defineProperty(unreadable, "text", {
      value: () => Promise.reject(new Error("download interrupted")),
    });
    presetBlobFailure(500, unreadable);

    const error = await captureError(blobExport());

    expect(error).toBeInstanceOf(HttpError);
    expect((error as HttpError).code).toBe(500);
    expect((error as HttpError).message).toBe("i18n:httpMsg.internalServerError");
  });

  it("401 下载失败仍走静默续期，不被错误体 msg 短路", async () => {
    mocks.refreshToken.mockRejectedValue(new Error("refresh 401"));
    presetBlobFailure(401, JSON.stringify({ code: 10401, msg: "令牌已过期" }));

    const error = await captureError(blobExport());

    expect(mocks.refreshToken).toHaveBeenCalledTimes(1);
    expect(mocks.redirectToLogin).toHaveBeenCalledWith("登录已失效，请重新登录");
    expect((error as HttpError).code).toBe(401);
    // 未被 Blob 错误体的 msg 短路
    expect(mocks.error).not.toHaveBeenCalledWith("令牌已过期");
  });

  it("成功下载（200 + 二进制流）路径零改动：原样返回 Blob 且不弹提示", async () => {
    const binary = new Blob([new Uint8Array([0x50, 0x4b, 0x03, 0x04])]);
    preset(ok(binary));

    const response = await blobExport();

    expect(response.data).toBe(binary);
    expect(mocks.error).not.toHaveBeenCalled();
    expect(mocks.success).not.toHaveBeenCalled();
  });
});

// ────────────── 3. 401 静默续期（含重放） ──────────────

describe("401 静默续期", () => {
  it("401 时刷新令牌并重放原请求，不弹错误提示", async () => {
    mocks.refreshToken.mockResolvedValue({
      data: { data: { access_token: "new-token", refresh_token: "new-refresh" } },
    });
    mocks.getAccessToken.mockReturnValue("new-token");
    preset(
      { kind: "fail", status: 401, data: { code: 10401, msg: "令牌已过期" } },
      ok({ code: 0, msg: "ok", data: { hit: true } })
    );

    const response = await request.get("/demo");

    expect(mocks.refreshToken).toHaveBeenCalledWith("refresh-1");
    expect(mocks.setTokens).toHaveBeenCalledWith("new-token", "new-refresh", false);
    expect(response.data).toEqual({ code: 0, msg: "ok", data: { hit: true } });
    expect(mocks.error).not.toHaveBeenCalled();
    // 第二次请求（重放）带着新令牌
    expect(seenConfigs).toHaveLength(2);
    expect(seenConfigs[1]?.headers.Authorization).toBe("Bearer new-token");
  });

  it("刷新失败时跳转登录页并拒绝请求", async () => {
    mocks.refreshToken.mockRejectedValue(new Error("refresh 401"));

    preset({ kind: "fail", status: 401, data: { code: 10401, msg: "令牌已过期" } });

    const error = await captureError(request.get("/demo"));

    expect(mocks.redirectToLogin).toHaveBeenCalledWith("令牌已过期");
    expect((error as HttpError).code).toBe(401);
  });
});

// ────────────── 4. handleError 与拦截器同口径 ──────────────

describe("handleError（useTable 等使用的导出函数）", () => {
  const config = {} as InternalAxiosRequestConfig;

  // handleError 是同步函数（throw，不返回 Promise），故用 toThrow 断言
  it("优先使用后端 msg，不再只按状态码映射文案", () => {
    const error = buildHttpError(config, 500, {
      code: 4500,
      msg: "导出失败: 磁盘空间不足",
      data: null,
    });

    expect(() => handleError(error)).toThrow("导出失败: 磁盘空间不足");
  });

  it("后端无 msg 时按状态码兜底", () => {
    const error = buildHttpError(config, 503, { code: 4503, data: null });

    expect(() => handleError(error)).toThrow("i18n:httpMsg.serviceUnavailable");
  });

  it("取消的请求不读取响应体，抛通用取消文案", () => {
    const canceled = new AxiosError<ApiResponse>("canceled", "ERR_CANCELED");

    expect(() => handleError(canceled)).toThrow("i18n:httpMsg.requestCancelled");
  });

  it("无响应体时抛网络错误文案", () => {
    expect(() => handleError(new AxiosError<ApiResponse>("Network Error"))).toThrow(
      "i18n:httpMsg.networkError"
    );
  });
});

// ────────────── 5. 成功路径不受影响 ──────────────

describe("成功路径", () => {
  it("code=0 的 GET 请求正常返回，且不弹任何提示", async () => {
    preset(ok({ code: 0, msg: "查询成功", data: { list: [] } }));

    const response = await request.get("/demo");

    expect(response.data.data).toEqual({ list: [] });
    expect(mocks.error).not.toHaveBeenCalled();
    expect(mocks.success).not.toHaveBeenCalled();
  });
});
