import { useEffect, useRef, useState } from 'react';

function selectContents(element) {
  const selection = window.getSelection();
  const range = document.createRange();
  range.selectNodeContents(element);
  selection.removeAllRanges();
  selection.addRange(range);
}

/**
 * Copying links: `copy(key, url)` puts `url` on the clipboard and marks `key`
 * copied for a moment (`copied`); where the browser refuses (an insecure
 * origin, say) the link is shown selected instead (`manual`, in the element
 * `urlRef` -- see CopyStatus in components/dashboard/share-link-buttons.jsx),
 * to copy by hand. The BDE's booking links and a Demo invitation share it.
 */
export function useLinkCopy() {
  const [copied, setCopied] = useState(null);
  const [manual, setManual] = useState(null);
  const urlRef = useRef(null);

  useEffect(() => {
    if (!copied) return undefined;
    const timer = setTimeout(() => setCopied(null), 2000);
    return () => clearTimeout(timer);
  }, [copied]);

  useEffect(() => {
    if (manual && urlRef.current) selectContents(urlRef.current);
  }, [manual]);

  const copy = async (key, url) => {
    try {
      await navigator.clipboard.writeText(url);
      setManual(null);
      setCopied(key);
    } catch {
      setCopied(null);
      setManual({ key, url });
    }
  };

  return { copied, manual, urlRef, copy };
}
