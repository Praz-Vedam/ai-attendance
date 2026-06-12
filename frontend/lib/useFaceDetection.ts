import { useEffect, useRef, useState } from "react";

export type FaceDetectionState = {
  detected: boolean;
  aligned: boolean;
  faceBox: {
    x: number;
    y: number;
    width: number;
    height: number;
  } | null;
  message: string;
  faceCenterX: number | null;
  faceCenterY: number | null;
  faceWidth: number | null;
  faceHeight: number | null;
  yaw: number | null;
  shouldersVisible: boolean;
  isCentered: boolean;
  isSizeValid: boolean;
  isFullyVisible: boolean;
  poseValid: boolean;
  failureReason: string | null;
};

const FACE_MIN_WIDTH_RATIO = 0.12;
const FACE_MAX_WIDTH_RATIO = 0.68;
const CENTER_TOLERANCE = 0.15;
const EDGE_TOLERANCE = 0.03;

const INITIAL_STATE: FaceDetectionState = {
  detected: false,
  aligned: false,
  faceBox: null,
  message: "Center your face",
  faceCenterX: null,
  faceCenterY: null,
  faceWidth: null,
  faceHeight: null,
  yaw: null,
  shouldersVisible: false,
  isCentered: false,
  isSizeValid: false,
  isFullyVisible: false,
  poseValid: true,
  failureReason: "face not detected",
};

function detectSkinTones(imageData: ImageData): Array<{ x: number; y: number }> {
  const data = imageData.data;
  const width = imageData.width;
  const skinPixels: Array<{ x: number; y: number }> = [];

  for (let i = 0; i < data.length; i += 4) {
    const r = data[i];
    const g = data[i + 1];
    const b = data[i + 2];
    const a = data[i + 3];

    // Skip transparent pixels
    if (a < 200) continue;

    // Improved skin detection: HSV-based heuristic
    // Check if pixel has skin-like characteristics
    const max = Math.max(r, g, b);
    const min = Math.min(r, g, b);
    const lightness = (max + min) / 2 / 255;

    // Filter out very dark and very light pixels
    if (lightness < 0.2 || lightness > 0.95) continue;

    // Skin tone check: red channel should be dominant
    if (r > g && r > b) {
      const rg_diff = r - g;
      const rb_diff = r - b;
      // Check for skin tone characteristics
      if (rg_diff >= 0 && rb_diff >= 0) {
        // More lenient thresholds for diverse skin tones
        if (r > 50) {
          const pixelIndex = i / 4;
          const x = pixelIndex % width;
          const y = Math.floor(pixelIndex / width);
          skinPixels.push({ x, y });
        }
      }
    }
  }

  return skinPixels;
}

function getBoundingBox(
  pixels: Array<{ x: number; y: number }>
): { x: number; y: number; width: number; height: number } | null {
  if (pixels.length === 0) return null;

  const xs = pixels.map((p) => p.x);
  const ys = pixels.map((p) => p.y);

  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);

  return {
    x: minX,
    y: minY,
    width: maxX - minX,
    height: maxY - minY,
  };
}

function getPercentileBoundingBox(
  pixels: Array<{ x: number; y: number }>
): { x: number; y: number; width: number; height: number } | null {
  if (pixels.length === 0) return null;

  const xs = pixels.map((p) => p.x).sort((a, b) => a - b);
  const ys = pixels.map((p) => p.y).sort((a, b) => a - b);
  const pick = (values: number[], percentile: number) =>
    values[Math.min(values.length - 1, Math.floor(values.length * percentile))];

  const minX = pick(xs, 0.16);
  const maxX = pick(xs, 0.84);
  const minY = pick(ys, 0.12);
  const maxY = pick(ys, 0.9);

  return {
    x: minX,
    y: minY,
    width: Math.max(0, maxX - minX),
    height: Math.max(0, maxY - minY),
  };
}

function estimateYaw(
  faceBox: { x: number; y: number; width: number; height: number },
  pixels: Array<{ x: number; y: number }>
): number {
  const facePixels = pixels.filter(
    (pixel) =>
      pixel.x >= faceBox.x &&
      pixel.x <= faceBox.x + faceBox.width &&
      pixel.y >= faceBox.y &&
      pixel.y <= faceBox.y + faceBox.height
  );

  if (facePixels.length === 0 || faceBox.width === 0) return 0;

  const averageX =
    facePixels.reduce((sum, pixel) => sum + pixel.x, 0) / facePixels.length;
  const faceCenterX = faceBox.x + faceBox.width / 2;
  const normalizedOffset = (averageX - faceCenterX) / faceBox.width;
  const deadZone = 0.04;
  const turnOffset = Math.max(0, Math.abs(normalizedOffset) - deadZone);

  return Math.sign(normalizedOffset) * Math.min(30, turnOffset * 220);
}

function isFaceAligned(
  faceBox: { x: number; y: number; width: number; height: number },
  videoWidth: number,
  videoHeight: number,
  context: "register" | "attendance",
  yaw: number
): Pick<
  FaceDetectionState,
  | "aligned"
  | "message"
  | "faceCenterX"
  | "faceCenterY"
  | "faceWidth"
  | "faceHeight"
  | "yaw"
  | "shouldersVisible"
  | "isCentered"
  | "isSizeValid"
  | "isFullyVisible"
  | "poseValid"
  | "failureReason"
> {
  const faceWidthRatio = faceBox.width / videoWidth;
  const faceCenterX = faceBox.x + faceBox.width / 2;
  const videoCenterX = videoWidth / 2;
  const horizontalOffset = Math.abs(faceCenterX - videoCenterX) / videoWidth;
  const faceCenterY = faceBox.y + faceBox.height / 2;
  const videoCenterY = videoHeight / 2;
  const verticalOffset = Math.abs(faceCenterY - videoCenterY) / videoHeight;

  const isCentered =
    horizontalOffset <= CENTER_TOLERANCE && verticalOffset <= CENTER_TOLERANCE;
  const isTooFar = faceWidthRatio < FACE_MIN_WIDTH_RATIO;
  const isTooClose =
    context === "register" &&
    faceWidthRatio > FACE_MAX_WIDTH_RATIO;
  const isSizeValid = !isTooFar && !isTooClose;
  const edgeToleranceX = videoWidth * EDGE_TOLERANCE;
  const edgeToleranceY = videoHeight * EDGE_TOLERANCE;
  const isFullyVisible =
    faceBox.x >= -edgeToleranceX &&
    faceBox.y >= -edgeToleranceY &&
    faceBox.x + faceBox.width <= videoWidth + edgeToleranceX &&
    faceBox.y + faceBox.height <= videoHeight + edgeToleranceY;
  const shouldersVisible =
    faceBox.y + faceBox.height < videoHeight * 0.95 &&
    faceCenterY < videoHeight * 0.76;
  const shouldersRequired = context === "register";
  const poseValid = true;

  const base = {
    faceCenterX,
    faceCenterY,
    faceWidth: faceBox.width,
    faceHeight: faceBox.height,
    yaw,
    shouldersVisible,
    isCentered,
    isSizeValid,
    isFullyVisible,
    poseValid,
  };

  if (!isCentered) {
    return {
      ...base,
      aligned: false,
      message: "Center your face",
      failureReason: "face not centered",
    };
  }

  if (isTooFar) {
    return {
      ...base,
      aligned: false,
      message: "Move closer to the camera",
      failureReason: "face too far",
    };
  }

  if (isTooClose) {
    return {
      ...base,
      aligned: false,
      message: "Move slightly backward",
      failureReason: "face too close",
    };
  }

  if (!isFullyVisible) {
    return {
      ...base,
      aligned: false,
      message: "Keep your full face visible",
      failureReason: "face not fully visible",
    };
  }

  if (shouldersRequired && !shouldersVisible) {
    return {
      ...base,
      aligned: false,
      message: "Show shoulders inside guide",
      failureReason: "shoulders not visible",
    };
  }

  return {
    ...base,
    aligned: true,
    message: "Face Aligned",
    failureReason: null,
  };
}

export function useFaceDetection(
  videoRef: React.RefObject<HTMLVideoElement | null>,
  context: "register" | "attendance" = "register"
) {
  const [state, setState] = useState<FaceDetectionState>(INITIAL_STATE);

  const animationFrameRef = useRef<number | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const lastProcessTimeRef = useRef<number>(0);

  useEffect(() => {
    let stopped = false;

    async function detectFace() {
      if (stopped) return;

      if (!videoRef.current) {
        animationFrameRef.current = requestAnimationFrame(detectFace);
        return;
      }

      const video = videoRef.current;
      if (video.videoWidth === 0 || video.videoHeight === 0) {
        animationFrameRef.current = requestAnimationFrame(detectFace);
        return;
      }

      const now = performance.now();
      if (now - lastProcessTimeRef.current < 100) {
        animationFrameRef.current = requestAnimationFrame(detectFace);
        return;
      }
      lastProcessTimeRef.current = now;

      try {
        if (!canvasRef.current) {
          canvasRef.current = document.createElement("canvas");
        }

        const canvas = canvasRef.current;
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;

        const ctx = canvas.getContext("2d");
        if (!ctx) {
          animationFrameRef.current = requestAnimationFrame(detectFace);
          return;
        }

        ctx.drawImage(video, 0, 0);
        const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);

        const skinPixels = detectSkinTones(imageData);
        const minSkinPixels = (canvas.width * canvas.height) / 200;

        if (skinPixels.length > minSkinPixels) {
          const faceBox =
            getPercentileBoundingBox(skinPixels) ?? getBoundingBox(skinPixels);

          if (faceBox && faceBox.width > 20 && faceBox.height > 20) {
            const yaw = estimateYaw(faceBox, skinPixels);
            const alignmentResult = isFaceAligned(
              faceBox,
              canvas.width,
              canvas.height,
              context,
              yaw
            );

            setState({
              detected: true,
              faceBox,
              ...alignmentResult,
            });
          } else {
            setState({
              ...INITIAL_STATE,
              message: "Center your face",
            });
          }
        } else {
          setState({
            ...INITIAL_STATE,
            message: "Center your face",
          });
        }
      } catch {
        setState((prev) => ({
          ...prev,
          detected: false,
          aligned: false,
        }));
      }

      animationFrameRef.current = requestAnimationFrame(detectFace);
    }

    animationFrameRef.current = requestAnimationFrame(detectFace);
    return () => {
      stopped = true;
      if (animationFrameRef.current) {
        cancelAnimationFrame(animationFrameRef.current);
      }
    };
  }, [videoRef, context]);

  return state;
}
