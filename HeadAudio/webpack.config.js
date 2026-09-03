// webpack.config.js
import path from "path";
import TerserPlugin from "terser-webpack-plugin";

export default {
  mode: "production",
  entry: {
    headaudio: "./modules/headaudio.mjs",
    headworklet: "./modules/headworklet.mjs",
  },
  output: {
    path: path.resolve('dist'),
    filename: '[name].min.mjs',
    library: {
      type: 'module' // output as an ES module library
    },
    module: true, // emit ES module syntax
    environment: { module: true }
  },
  experiments: {
    outputModule: true, // required for ES module output
  },
  optimization: {
    minimize: true, // minify the output
    minimizer: [
      new TerserPlugin({
        extractComments: false, // no LICENSE.txt files
        terserOptions: {
          compress: { defaults: true, unused: false },
          keep_classnames: true
        },
      }),
    ],
    sideEffects: true
  },
  module: {
    rules: [
      {
        test: /\.mjs$/,
        type: "javascript/auto", // allow Webpack to parse .mjs properly
      },
    ],
  },
  resolve: {
    extensions: [".mjs"],
  }
};