import type { ProviderId, ProviderInfo } from "./api";
import type { useI18n } from "../i18n";

type T = ReturnType<typeof useI18n>["t"];

/** Description d'un fournisseur dans la langue de la console (le serveur ne renvoie que des champs bruts utiles). */
export function describeProvider(id: ProviderId, info: ProviderInfo, t: T): ProviderInfo {
  if (id === "claude") {
    return { ...info, name: "Claude", vendor: "Anthropic", detail: t("provider.claude.detail"), hosting: t("provider.claude.hosting") };
  }
  const parts = [info.model ? t("provider.trusted.model", { model: info.model }) : "", info.host ?? ""].filter(Boolean);
  return {
    ...info,
    name: info.custom_name ? info.name : t("provider.trusted.defaultName"),
    vendor: t("provider.trusted.vendor"),
    detail: parts.length ? parts.join(" · ") : t("provider.trusted.notConfigured"),
    hosting: t("provider.trusted.hosting"),
  };
}
