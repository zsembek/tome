// Markdown renderer with GFM (tables), signed image URLs, and basic typography.
import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { signAssetUrls } from "../lib/api";

export function Markdown({ children }: { children: string }) {
  // Replace /v1/assets/.. with short-lived signed URLs (for <img src>).
  const [md, setMd] = useState(children || "");
  useEffect(() => {
    let alive = true;
    signAssetUrls(children || "").then((s) => { if (alive) setMd(s); });
    return () => { alive = false; };
  }, [children]);
  return (
    <div className="md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: (p) => <h1 className="text-xl font-bold mt-4 mb-2" {...p} />,
          h2: (p) => <h2 className="text-lg font-semibold mt-3 mb-2" {...p} />,
          h3: (p) => <h3 className="text-base font-semibold mt-2 mb-1" {...p} />,
          p: (p) => <p className="my-2 leading-relaxed" {...p} />,
          ul: (p) => <ul className="list-disc ml-6 my-2" {...p} />,
          ol: (p) => <ol className="list-decimal ml-6 my-2" {...p} />,
          table: (p) => <table className="border-collapse my-3 text-sm" {...p} />,
          th: (p) => <th className="border border-line px-2 py-1 bg-[#1e252e]" {...p} />,
          td: (p) => <td className="border border-line px-2 py-1" {...p} />,
          code: (p) => <code className="bg-[#0b0e12] border border-line rounded px-1 py-0.5 text-xs" {...p} />,
          blockquote: (p) => <blockquote className="border-l-2 border-acc/50 pl-3 my-2 text-mut" {...p} />,
          img: (p) => <img className="max-w-full rounded border border-line my-2" loading="lazy" {...p} />,
          a: (p) => <a className="text-acc underline" target="_blank" {...p} />,
        }}
      >
        {md}
      </ReactMarkdown>
    </div>
  );
}
