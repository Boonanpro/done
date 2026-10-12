import {useEffect} from 'react';
import {Platform} from 'react-native';
import * as Orientation from 'expo-screen-orientation';

// Serialize opening/closing so a quickly reopened gallery cannot inherit a late
// portrait reset from the previous gallery.
let orientationChanges=Promise.resolve();
function changeOrientation(action:()=>Promise<void>){
 orientationChanges=orientationChanges.then(action).catch(error=>{
  console.warn('Could not update media orientation',error);
 });
}
export function useMediaRotation(){
 useEffect(()=>{
  if(Platform.OS==='web')return;
  let previous=Orientation.OrientationLock.PORTRAIT_UP;
  changeOrientation(async()=>{
   const lock=await Orientation.getOrientationLockAsync();
   if(lock!==Orientation.OrientationLock.UNKNOWN&&lock!==Orientation.OrientationLock.OTHER)previous=lock;
   await Orientation.lockAsync(Platform.OS==='android'?Orientation.OrientationLock.ALL:Orientation.OrientationLock.DEFAULT);
  });
  return()=>changeOrientation(()=>Orientation.lockAsync(previous));
 },[]);
}
