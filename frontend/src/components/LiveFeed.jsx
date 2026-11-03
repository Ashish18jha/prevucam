import { useEffect, useState } from "react";
import Icon from "./Icons";
import { streamUrl } from "../services/api";
import { useLive } from "../context/LiveContext";
import { useWebcam } from "../context/WebcamContext";
import WebcamView from "./WebcamView";

/** MJPEG live view. Boxes, labels, tracking IDs and zones are rendered server-side. */
export default function LiveFeed({ overlay = true }) {
  const { camera } = useLive();
  const webcam = useWebcam();
  const live = camera?.running && camera?.connected;
  const [nonce, setNonce] = useState(0);
  const [broken, setBroken] = useState(false);

  useEffect(() => { if (live) { setNonce((n) => n + 1); setBroken(false); } }, [live, overlay]);

  if (webcam?.stream || webcam?.error) return <WebcamView overlay={overlay} />;

  return (
    <div className="feed">
      {live && !broken ? (
        <img src={streamUrl(overlay, nonce)} alt="Live camera" onError={() => setBroken(true)} />
      ) : (
        <div className="feed-off">
          <div>
            <Icon name="off" />
            <div>{camera?.running ? (camera?.error || "Connecting to source…") : "Camera is stopped – press Start to use your webcam"}</div>
            <div className="faint" style={{ fontSize: 12, marginTop: 4 }}>
              {camera ? `${camera.source_type} · ${camera.source}` : "Backend unreachable"}
            </div>
          </div>
        </div>
      )}
      <span className="corner tl" /><span className="corner tr" /><span className="corner bl" /><span className="corner br" />
    </div>
  );
}
