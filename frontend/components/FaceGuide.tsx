"use client";

const GUIDE_STROKE_COLOR = "rgba(255, 255, 255, 0.75)";
const GUIDE_STROKE_WIDTH = 3;
const VIEWBOX = "0 0 1280 720";

const FrontGuide = () => (
  <svg
    width="100%"
    height="100%"
    viewBox={VIEWBOX}
    preserveAspectRatio="none"
    style={{ position: "absolute", top: 0, left: 0 }}
  >
    <ellipse
      cx="640"
      cy="300"
      rx="140"
      ry="190"
      fill="none"
      stroke={GUIDE_STROKE_COLOR}
      strokeWidth={GUIDE_STROKE_WIDTH}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    <path
      d="M 540 480 Q 640 550 740 480 L 740 600 Q 640 630 540 600 Z"
      fill="none"
      stroke={GUIDE_STROKE_COLOR}
      strokeWidth={GUIDE_STROKE_WIDTH}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

const LeftGuide = () => (
  <svg
    width="100%"
    height="100%"
    viewBox={VIEWBOX}
    preserveAspectRatio="none"
    style={{ position: "absolute", top: 0, left: 0 }}
  >
    <path
      d="M 580 140
        Q 540 165 525 215
        L 520 280
        Q 518 330 530 380
        L 545 430
        Q 560 470 575 510
        L 595 570
        Q 615 600 650 640
        L 750 690
        L 820 650
        Q 840 600 825 570
        L 805 510
        Q 820 470 835 430
        L 850 380
        Q 862 330 860 280
        L 855 215
        Q 840 165 800 140
        Q 750 120 680 115
        Q 630 112 580 140
        Z"
      fill="none"
      stroke={GUIDE_STROKE_COLOR}
      strokeWidth={GUIDE_STROKE_WIDTH}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

const RightGuide = () => (
  <svg
    width="100%"
    height="100%"
    viewBox={VIEWBOX}
    preserveAspectRatio="none"
    style={{ position: "absolute", top: 0, left: 0 }}
  >
    <path
      d="M 700 140
        Q 740 165 755 215
        L 760 280
        Q 762 330 750 380
        L 735 430
        Q 720 470 705 510
        L 685 570
        Q 665 600 630 640
        L 530 690
        L 460 650
        Q 440 600 455 570
        L 475 510
        Q 460 470 445 430
        L 430 380
        Q 418 330 420 280
        L 425 215
        Q 440 165 480 140
        Q 530 120 600 115
        Q 650 112 700 140
        Z"
      fill="none"
      stroke={GUIDE_STROKE_COLOR}
      strokeWidth={GUIDE_STROKE_WIDTH}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

interface FaceGuideProps {
  step: number;
}

export const FaceGuide: React.FC<FaceGuideProps> = ({ step }) => {
  const getGuideStyle = (guideStep: number) => ({
    position: "absolute" as const,
    inset: 0,
    opacity: step === guideStep ? 1 : 0,
    transition: "opacity 350ms cubic-bezier(0.4, 0, 0.2, 1)",
    pointerEvents: "none" as const,
  });

  return (
    <>
      <div style={getGuideStyle(0)}>
        <FrontGuide />
      </div>
      <div style={getGuideStyle(1)}>
        <LeftGuide />
      </div>
      <div style={getGuideStyle(2)}>
        <RightGuide />
      </div>
    </>
  );
};
