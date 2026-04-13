import { Composition } from "remotion";
import { YoshikawaProposal } from "./YoshikawaProposal";

// Recording: 1022 frames
// + Intro 90 + Text1 90 + Text2 90 + Outro 90 = 1382
export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="YoshikawaProposal"
      component={YoshikawaProposal}
      durationInFrames={1382}
      fps={30}
      width={1920}
      height={1080}
    />
  );
};
