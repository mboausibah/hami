import { send } from "../lib/messages";

const done = document.getElementById("done")!;

async function choose(agree: boolean): Promise<void> {
  const res = await send({ type: "consent", agree });
  done.hidden = false;
  done.textContent = !res.ok
    ? `Error: ${res.error}`
    : agree
      ? "Automatic checking is on. You can turn it off in Hami's settings. · تم تفعيل الفحص التلقائي ويمكنك إيقافه من الإعدادات."
      : "Automatic checking stays off. · يبقى الفحص التلقائي معطلًا.";
}

document.getElementById("agree")!.addEventListener("click", () => void choose(true));
document.getElementById("decline")!.addEventListener("click", () => void choose(false));
