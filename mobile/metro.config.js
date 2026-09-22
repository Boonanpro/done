const path = require('path');
const { getDefaultConfig } = require('expo/metro-config');
const config = getDefaultConfig(__dirname);
// Share transport-independent Live controllers with the dashboard.
config.watchFolders = [path.resolve(__dirname, '../frontend/src/components/voice')];
module.exports = config;
