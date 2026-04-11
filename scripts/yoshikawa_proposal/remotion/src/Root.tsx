import { Composition } from "remotion";
import { YoshikawaProposal } from "./YoshikawaProposal";

// Total: intro(90) + recording(642) + text1(90) + text2(90) + outro(90) = ~1002
// But recording frames are interleaved with text inserts via Sequences
export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="YoshikawaProposal"
      component={YoshikawaProposal}
      durationInFrames={1325}
      fps={30}
      width={1920}
      height={1080}
    />
  );
};
