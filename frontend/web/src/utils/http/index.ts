/**
 * HTTP：Axios 实例、约定常量、错误类型与拦截器（单文件聚合）
 */

import axios, {
  type AxiosError,
  type AxiosInstance,
  type AxiosRequestConfig,
  type AxiosResponse,
  type InternalAxiosRequestConfig,
} from "axios";
import qs from "qs";
import { ElMessage } from "element-plus";
import { Auth } from "@/utils/auth";
import { redirectToLogin } from "@/utils/auth";
import { $t } from "@/locales";
import AuthAPI from "@/api/module_system/auth";
import { ResultEnum } from "@/enums/api/result.enum";

// --- 配置常量 -----------------------------------------------------------------

/** 跳过鉴权标记：接口 headers.Authorization 设为该值时不带 token 请求 */
export const NO_AUTH_FLAG = "no-auth";

export interface ExtendedRequestConfig extends AxiosRequestConfig {
  skipAuth?: boolean;
  showSuccessMessage?: boolean;
  showErrorMessage?: boolean;
}

// --- 语义状态码与 HttpError ----------------------------------------------------

export enum ApiStatus {
  success = 200,
  error = 400,
  unauthorized = 401,
  forbidden = 403,
  notFound = 404,
  methodNotAllowed = 405,
  requestTimeout = 408,
  internalServerError = 500,
  notImplemented = 501,
  badGateway = 502,
  serviceUnavailable = 503,
  gatewayTimeout = 504,
  httpVersionNotSupported = 505,
}

export interface ErrorLogData {
  code: number;
  message: string;
  data?: unknown;
  timestamp: string;
  url?: string;
  method?: string;
  stack?: string;
}

export class HttpError extends Error {
  public readonly code: number;
  public readonly data?: unknown;
  public readonly timestamp: string;
  public readonly url?: string;
  public readonly method?: string;

  constructor(
    message: string,
    code: number,
    options?: {
      data?: unknown;
      url?: string;
      method?: string;
    }
  ) {
    super(message);
    this.name = "HttpError";
    this.code = code;
    this.data = options?.data;
    this.timestamp = new Date().toISOString();
    this.url = options?.url;
    this.method = options?.method;
  }

  public toLogData(): ErrorLogData {
    return {
      code: this.code,
      message: this.message,
      data: this.data,
      timestamp: this.timestamp,
      url: this.url,
      method: this.method,
      stack: this.stack,
    };
  }
}

/**
 * HTTP 状态码 → 兜底文案 key。
 *
 * 这是**兜底**映射：只在后端没有返回 `msg` 时才使用。
 * （后端业务码已收敛为单一事实来源，`RET.code → HTTP status`，所以前端不再按业务码
 * 挑选文案，详情见下方响应拦截器的「业务错误」分支。）
 *
 * 显式收录 400 → 通用「请求失败」：旧实现在业务码未命中白名单时统一走 else 分支显示
 * 「请求失败」，收录后这条路径的文案与旧行为保持一致。
 * 未收录的状态码（409/422/429…）同样退化为通用「请求失败」，比「服务器内部错误」更准确。
 */
const STATUS_MESSAGE_KEYS: Record<number, string> = {
  [ApiStatus.error]: "httpMsg.requestFailed",
  [ApiStatus.unauthorized]: "httpMsg.unauthorized",
  [ApiStatus.forbidden]: "httpMsg.forbidden",
  [ApiStatus.notFound]: "httpMsg.notFound",
  [ApiStatus.methodNotAllowed]: "httpMsg.methodNotAllowed",
  [ApiStatus.requestTimeout]: "httpMsg.requestTimeout",
  [ApiStatus.internalServerError]: "httpMsg.internalServerError",
  [ApiStatus.badGateway]: "httpMsg.badGateway",
  [ApiStatus.serviceUnavailable]: "httpMsg.serviceUnavailable",
  [ApiStatus.gatewayTimeout]: "httpMsg.gatewayTimeout",
};

/** 状态码兜底文案（未收录的状态码退化为通用「请求失败」） */
const getErrorMessage = (status: number): string =>
  $t(STATUS_MESSAGE_KEYS[status] || "httpMsg.requestFailed");

/**
 * 业务码兜底文案（仅用于后端未返回 `msg` 的情况）。
 * 未知业务码返回 `undefined`，让调用方继续按 HTTP 状态码回退。
 */
const getCodeFallbackMessage = (code?: number): string | undefined => {
  switch (code) {
    case ResultEnum.ERROR:
      return $t("httpMsg.requestFailed");
    case ResultEnum.EXCEPTION:
      return $t("httpMsg.internalServerError");
    case ResultEnum.UNAUTHORIZED:
      return $t("httpMsg.unauthorized");
    default:
      return undefined;
  }
};

/**
 * 从 Blob 错误体里读取后端 msg（文件下载失败场景）。
 *
 * `responseType: "blob"` 时，后端返回的 JSON 错误体也会被包成 Blob，所以这里主动解析一次：
 * - 能解析出对象且 `code` 是非成功业务码 → 返回其后端 `msg`（错误码已收敛为单一事实来源，
 *   不再只认 `ERROR(1)`/`EXCEPTION(-1)`，4500/404/4090 等同样能取到诊断信息）；
 * - 有业务码但没 msg → 返回原有业务码兜底文案（保留 1/-1 的旧口径）；
 * - 解析不出结构化错误体（真正的二进制内容 / 空内容 / 下载中断 / 非 JSON）→ 返回 `undefined`，
 *   由调用方按 HTTP 状态码兜底。
 *
 * 本函数保证不抛异常：任何异常都只记录日志并返回 `undefined`。
 */
const readBlobErrorMessage = async (blob: Blob): Promise<string | undefined> => {
  try {
    const text = await new Response(blob).text();
    if (!text.trim()) return undefined;

    const jsonData = JSON.parse(text) as ApiResponse | null;
    if (!jsonData || typeof jsonData.code !== "number" || jsonData.code === ResultEnum.SUCCESS) {
      return undefined;
    }

    return jsonData.msg || getCodeFallbackMessage(jsonData.code);
  } catch (error) {
    console.error("[下载错误体解析失败]", error);
    return undefined;
  }
};

export function handleError(error: AxiosError<ApiResponse>): never {
  if (error.code === "ERR_CANCELED") {
    console.info("Request cancelled:", error.message);
    throw new HttpError($t("httpMsg.requestCancelled"), ApiStatus.error);
  }

  const statusCode = error.response?.status;
  const requestConfig = error.config;

  if (!error.response) {
    throw new HttpError($t("httpMsg.networkError"), ApiStatus.error, {
      url: requestConfig?.url,
      method: requestConfig?.method?.toUpperCase(),
    });
  }

  // 与响应拦截器同口径：后端 msg 优先（保留其诊断信息），缺失时再按状态码兜底
  const message =
    error.response.data?.msg ||
    (statusCode ? getErrorMessage(statusCode) : "") ||
    $t("httpMsg.requestFailed");
  throw new HttpError(message, statusCode || ApiStatus.error, {
    data: error.response.data,
    url: requestConfig?.url,
    method: requestConfig?.method?.toUpperCase(),
  });
}

export function showError(error: HttpError, showMessage: boolean = true): void {
  if (showMessage) {
    ElMessage.error(error.message);
  }
  console.error("[HTTP Error]", error.toLogData());
}

export function showSuccess(message: string, showMessage: boolean = true): void {
  if (showMessage) {
    ElMessage.success(message);
  }
}

export const isHttpError = (error: unknown): error is HttpError => {
  return error instanceof HttpError;
};

// --- Token 刷新去重 -----------------------------------------------------------

/**
 * token 刷新进行中标识，避免并发 401 触发多次 refresh 请求。
 * 配合 pendingRequests 队列，刷新成功后统一重放等待中的请求。
 */
let isRefreshing = false;
let pendingRequests: Array<{
  config: InternalAxiosRequestConfig;
  resolve: (value: Promise<AxiosResponse>) => void;
  reject: (reason?: Error) => void;
}> = [];

function onRefreshed(newToken: string) {
  const list = pendingRequests;
  pendingRequests = [];
  list.forEach(({ config, resolve }) => {
    config.headers.Authorization = `Bearer ${newToken}`;
    resolve(request(config));
  });
}

function onRefreshFailed() {
  pendingRequests.forEach(({ reject }) => reject(new Error("Token refresh failed")));
  pendingRequests = [];
}

// --- Axios 实例 ---------------------------------------------------------------

export const request: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_APP_BASE_API,
  timeout: Number(import.meta.env.VITE_API_TIMEOUT) || 15000,
  headers: { "Content-Type": "application/json;charset=utf-8" },
  paramsSerializer: (params) => qs.stringify(params, { indices: false }),
});

request.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const accessToken = Auth.getAccessToken();
    const auth = config.headers.Authorization;
    const extConfig = config as ExtendedRequestConfig;

    if (auth === NO_AUTH_FLAG || extConfig.skipAuth) {
      delete config.headers.Authorization;
      return config;
    }

    if (!auth && accessToken) {
      config.headers.Authorization = `Bearer ${accessToken}`;
    }

    return config;
  },
  (error) => {
    const msg = error instanceof Error ? error.message : String(error);
    ElMessage.error(msg);
    return Promise.reject(error);
  }
);

/**
 * 响应拦截器 —— 三层处理逻辑：
 *
 * 1. 成功响应（response）
 *    - blob 直通（文件下载不经过 JSON 解析）
 *    - 检查业务 code，非 SUCCESS 时报错
 *    - 非 GET 且非 login/logout 接口成功时显示成功消息
 *
 * 2. 网络错误（无 response）
 *    - 区分 ECONNREFUSED / timeout / Network Error，给出中文提示
 *
 * 3. 业务/鉴权错误（有 response）
 *    - Blob 响应错误 → 尝试解析 JSON 提取 msg
 *    - 401 / TOKEN_EXPIRED → 静默刷新 token，成功后重放待处理请求
 *    - 其他业务错误 → 按 code 分类提示
 */
request.interceptors.response.use(
  (response: AxiosResponse<ApiResponse>) => {
    if (response.config.responseType === "blob") {
      return response;
    }

    const data = response.data;
    const extConfig = response.config as ExtendedRequestConfig;

    if (data.code !== ResultEnum.SUCCESS) {
      if (extConfig.showErrorMessage !== false) {
        ElMessage.error(data.msg || $t("httpMsg.requestFailed"));
      }
      return Promise.reject(response);
    }

    if (
      response.config.method?.toUpperCase() !== "GET" &&
      !response.config.url?.includes("login") &&
      !response.config.url?.includes("logout")
    ) {
      if (extConfig.showSuccessMessage !== false && data.msg) {
        ElMessage.success(data.msg);
      }
    }

    return response;
  },
  async (error: AxiosError<ApiResponse>) => {
    // ── 请求被取消（ERR_CANCELED），静默处理，不弹错误提示 ──
    if (error.code === "ERR_CANCELED") {
      console.info("Request cancelled:", error.message);
      return Promise.reject(new HttpError($t("httpMsg.requestCancelled"), ApiStatus.error));
    }

    // ── 网络错误（无响应体） ──
    if (!error.response) {
      let errorMessage = $t("httpMsg.networkError");

      if (error.message?.includes("ECONNREFUSED")) {
        errorMessage = "服务器连接失败，请检查后端服务是否正常运行";
      } else if (error.message?.includes("timeout")) {
        errorMessage = $t("httpMsg.requestTimeout");
      } else if (error.message?.includes("Network Error")) {
        errorMessage = "网络连接错误，请检查您的网络设置";
      }

      console.error("网络请求失败:", error);
      ElMessage.error(errorMessage);
      return Promise.reject(new Error(errorMessage));
    }

    const data = error.response?.data;
    const status = error.response.status;

    // ── Blob 响应错误（文件下载场景） ──
    // 下载失败时后端返回的是 JSON 错误体，但 responseType=blob 让这里只能拿到 Blob，
    // 因此主动解析一次，使下载场景也能优先展示后端 msg（与下方业务错误分支同口径）。
    // 例外：HTTP 401 必须留给下面的「静默续期」，不能被这里的 msg 短路。
    if (status !== 401 && error.response.config.responseType === "blob" && data instanceof Blob) {
      const blobMessage = await readBlobErrorMessage(data);
      if (blobMessage) {
        ElMessage.error(blobMessage);
        return Promise.reject(new HttpError(blobMessage, status || ApiStatus.error));
      }
      // 拿不到结构化错误体（真正的二进制内容 / 空内容 / 下载中断）：
      // 不抛额外异常，继续走下面的状态码兜底
    }

    // ── 鉴权错误（401 / TOKEN_EXPIRED）：静默续期 ──
    if (status === 401 || data?.code === ResultEnum.TOKEN_EXPIRED) {
      const config = error.config as InternalAxiosRequestConfig | undefined;

      // 若 refresh 接口自身返回 401，不在此处跳转登录 ——
      // 交由下方 catch 块的 redirectToLogin 统一处理，避免双通知
      if (config?.url?.endsWith("/auth/token/refresh")) {
        return Promise.reject(
          new HttpError(data?.msg || $t("httpMsg.unauthorized"), ApiStatus.unauthorized)
        );
      }

      // 无请求配置（罕见）或 logout 自身返回 401，直接跳转登录
      if (!config || config.url?.includes("auth/logout")) {
        await redirectToLogin($t("httpMsg.unauthorized"));
        return Promise.reject(new HttpError($t("httpMsg.unauthorized"), ApiStatus.unauthorized));
      }

      // 首次 401：发起 refresh；后续并发 401 入队等待
      if (!isRefreshing) {
        isRefreshing = true;
        try {
          // 直接请求刷新令牌接口，避免动态导入 user.store 造成循环依赖
          const refreshResp = await AuthAPI.refreshToken(Auth.getRefreshToken());
          const tokenData = refreshResp.data.data;
          const newAccessToken = tokenData?.access_token || "";
          const newRefreshToken = tokenData?.refresh_token || "";
          Auth.setTokens(newAccessToken, newRefreshToken, Auth.getRememberMe());
          isRefreshing = false;
          const newToken = Auth.getAccessToken();
          // 重放等待队列中的所有请求
          onRefreshed(newToken);
          // 用新 token 重试当前请求
          config.headers.Authorization = `Bearer ${newToken}`;
          return request(config);
        } catch {
          isRefreshing = false;
          // refresh 失败：拒绝队列中所有等待请求 + 跳转登录
          onRefreshFailed();
          const msg = data?.msg || "登录已失效，请重新登录";
          await redirectToLogin(msg);
          return Promise.reject(new HttpError(msg, ApiStatus.unauthorized));
        }
      } else {
        // 已有 refresh 进行中，将当前请求加入等待队列，刷新完成后自动重放
        return new Promise((resolve, reject) => {
          pendingRequests.push({ config: config!, resolve, reject });
        });
      }
    }

    // ── 无权限（403）：保持既有分支与文案优先级不变 ──
    if (status === 403) {
      ElMessage.error(data?.msg || $t("httpMsg.forbidden"));
      return Promise.reject(
        new HttpError(data?.msg || $t("httpMsg.forbidden"), ApiStatus.forbidden)
      );
    }

    // ── 业务错误 ──
    // 后端业务码与 HTTP 状态码已收敛为单一事实来源（RET.code → status），前端不再按
    // 业务码白名单挑选文案：只要后端给了 msg 就优先展示（保留其诊断信息，如
    // 「分页查询失败: 连接已断开」），缺失时才按「业务码 → 状态码 → 通用」回退。
    const message =
      data?.msg ||
      getCodeFallbackMessage(data?.code) ||
      (status ? getErrorMessage(status) : "") ||
      $t("httpMsg.requestFailed");

    ElMessage.error(message);
    return Promise.reject(
      new HttpError(
        message,
        data?.code === ResultEnum.UNAUTHORIZED ? ApiStatus.unauthorized : status || ApiStatus.error
      )
    );
  }
);

export type { AxiosInstance } from "axios";
